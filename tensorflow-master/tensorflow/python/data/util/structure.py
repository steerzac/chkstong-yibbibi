# Copyright 2018 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Utilities for describing the structure of a `tf.data` type."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import abc

from tensorflow.python.data.util import nest
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import ops
from tensorflow.python.framework import sparse_tensor as sparse_tensor_lib
from tensorflow.python.framework import tensor_shape
from tensorflow.python.framework import tensor_util
from tensorflow.python.ops import sparse_ops


_STRUCTURE_CONVERSION_FUNCTION_REGISTRY = {}


class Structure(object):
  """Represents structural information, such as type and shape, about a value.

  A `Structure` generalizes the `tf.Tensor.dtype` and `tf.Tensor.shape`
  properties, so that we can define generic containers of objects including:

  * `tf.Tensor`
  * `tf.SparseTensor`
  * Nested structures of the above.

  TODO(b/110122868): In the future, a single `Structure` will replace the
  `tf.data.Dataset.output_types`, `tf.data.Dataset.output_shapes`,
  and `tf.data.Dataset.output_classes`, and similar properties and arguments in
  the `tf.data.Iterator` and `Optional` classes.
  """
  __metaclass__ = abc.ABCMeta

  @abc.abstractproperty
  def _flat_shapes(self):
    """A list of shapes matching the shapes of `self._to_tensor_list()`.

    Returns:
      A list of `tf.TensorShape` objects.
    """
    raise NotImplementedError("Structure._flat_shapes")

  @abc.abstractproperty
  def _flat_types(self):
    """A list of types matching the types of `self._to_tensor_list()`.

    Returns:
      A list of `tf.DType` objects.
    """
    raise NotImplementedError("Structure._flat_shapes")

  @abc.abstractmethod
  def is_compatible_with(self, other):
    """Returns `True` if `other` is compatible with this structure.

    A structure `t` is a "subtype" of `s` if:

    * `s` and `t` are instances of the same `Structure` subclass.
    * The nested structures (if any) of `s` and `t` are the same, according to
      `tf.contrib.framework.nest.assert_same_structure`, and each nested
      structure of `t` is a "subtype" of the corresponding nested structure of
      `s`.
    * Any `tf.DType` components of `t` are the same as the corresponding
      components in `s`.
    * Any `tf.TensorShape` components of `t` are compatible with the
      corresponding components in `s`, according to
      `tf.TensorShape.is_compatible_with`.

    Args:
      other: A `Structure`.

    Returns:
      `True` if `other` is a subtype of this structure, otherwise `False`.
    """
    raise NotImplementedError("Structure.is_compatible_with()")

  @abc.abstractmethod
  def _to_tensor_list(self, value):
    """Returns a flat list of `tf.Tensor` representing `value`.

    This method can be used, along with `self._flat_shapes` and
    `self._flat_types` to represent structured values in lower level APIs
    (such as plain TensorFlow operations) that do not understand structure.

    Requires: `self.is_compatible_with(Structure.from_value(value))`.

    Args:
      value: A value with compatible structure.

    Returns:
      A flat list of `tf.Tensor` representing `value`.
    """
    raise NotImplementedError("Structure._to_tensor_list()")

  @abc.abstractmethod
  def _from_tensor_list(self, flat_value):
    """Builds a flat list of `tf.Tensor` into a value matching this structure.

    Requires: The shapes and types of the tensors in `flat_value` must be
    compatible with `self._flat_shapes` and `self._flat_types` respectively.

    Args:
      flat_value: A list of `tf.Tensor` with compatible flat structure.

    Returns:
      A structured object matching this structure.
    """
    raise NotImplementedError("Structure._from_tensor_list()")

  @staticmethod
  def from_value(value):
    """Returns a `Structure` that represents the given `value`.

    Args:
      value: A potentially structured value.

    Returns:
      A `Structure` that is compatible with `value`.

    Raises:
      TypeError: If a structure cannot be built for `value`, because its type
        or one of its component types is not supported.
    """
    # TODO(b/110122868): Add support for custom types and Dataset to this
    # method.
    if isinstance(
        value,
        (sparse_tensor_lib.SparseTensor, sparse_tensor_lib.SparseTensorValue)):
      return SparseTensorStructure.from_value(value)
    elif isinstance(value, (tuple, dict)):
      return NestedStructure.from_value(value)
    else:
      for converter_type, converter_fn in (
          _STRUCTURE_CONVERSION_FUNCTION_REGISTRY.items()):
        if isinstance(value, converter_type):
          return converter_fn(value)
      try:
        tensor = ops.convert_to_tensor(value)
      except (ValueError, TypeError):
        raise TypeError("Could not build a structure for %r" % value)
      return TensorStructure.from_value(tensor)

  @staticmethod
  def _from_legacy_structure(output_types, output_shapes, output_classes):
    """Returns a `Structure` that represents the given legacy structure.

    This method provides a way to convert from the existing `Dataset` and
    `Iterator` structure-related properties to a `Structure` object.

    TODO(b/110122868): Remove this method once `Structure` is used throughout
    `tf.data`.

    Args:
      output_types: A nested structure of `tf.DType` objects corresponding to
        each component of a structured value.
      output_shapes: A nested structure of `tf.TensorShape` objects
        corresponding to each component a structured value.
      output_classes: A nested structure of Python `type` objects corresponding
        to each component of a structured value.

    Returns:
      A `Structure`.

    Raises:
      TypeError: If a structure cannot be built the arguments, because one of
        the component classes in `output_classes` is not supported.
    """
    flat_types = nest.flatten(output_types)
    flat_shapes = nest.flatten(output_shapes)
    flat_classes = nest.flatten(output_classes)
    flat_ret = []
    for flat_type, flat_shape, flat_class in zip(flat_types, flat_shapes,
                                                 flat_classes):
      if issubclass(flat_class, sparse_tensor_lib.SparseTensor):
        flat_ret.append(SparseTensorStructure(flat_type, flat_shape))
      elif issubclass(flat_class, ops.Tensor):
        flat_ret.append(TensorStructure(flat_type, flat_shape))
      else:
        # NOTE(mrry): Since legacy structures produced by iterators only
        # comprise Tensors, SparseTensors, and nests, we do not need to support
        # all structure types here.
        raise TypeError(
            "Could not build a structure for output class %r" % flat_type)

    ret = nest.pack_sequence_as(output_classes, flat_ret)
    if isinstance(ret, Structure):
      return ret
    else:
      return NestedStructure(ret)

  @staticmethod
  def _register_custom_converter(type_object, converter_fn):
    """Registers `converter_fn` for converting values of the given type.

    Args:
      type_object: A Python `type` object representing the type of values
        accepted by `converter_fn`.
      converter_fn: A function that takes one argument (an instance of the
        type represented by `type_object`) and returns a `Structure`.
    """
    _STRUCTURE_CONVERSION_FUNCTION_REGISTRY[type_object] = converter_fn


# NOTE(mrry): The following classes make extensive use of non-public methods of
# their base class, so we disable the protected-access lint warning once here.
# pylint: disable=protected-access
class NestedStructure(Structure):
  """Represents a nested structure in which each leaf is a `Structure`."""

  def __init__(self, nested_structure):
    self._nested_structure = nested_structure
    self._flat_shapes_list = []
    self._flat_types_list = []
    for s in nest.flatten(nested_structure):
      if not isinstance(s, Structure):
        raise TypeError("nested_structure must be a (potentially nested) tuple "
                        "or dictionary of Structure objects.")
      self._flat_shapes_list.extend(s._flat_shapes)
      self._flat_types_list.extend(s._flat_types)

  @property
  def _flat_shapes(self):
    return self._flat_shapes_list

  @property
  def _flat_types(self):
    return self._flat_types_list

  def is_compatible_with(self, other):
    if not isinstance(other, NestedStructure):
      return False
    try:
      # pylint: disable=protected-access
      nest.assert_same_structure(self._nested_structure,
                                 other._nested_structure)
    except (ValueError, TypeError):
      return False

    return all(
        substructure.is_compatible_with(other_substructure)
        for substructure, other_substructure in zip(
            nest.flatten(self._nested_structure),
            nest.flatten(other._nested_structure)))

  def _to_tensor_list(self, value):
    ret = []

    try:
      flat_value = nest.flatten_up_to(self._nested_structure, value)
    except (ValueError, TypeError):
      raise ValueError("The value %r is not compatible with the nested "
                       "structure %r." % (value, self._nested_structure))

    for sub_value, structure in zip(flat_value,
                                    nest.flatten(self._nested_structure)):
      if not structure.is_compatible_with(Structure.from_value(sub_value)):
        raise ValueError("Component value %r is not compatible with the nested "
                         "structure %r." % (sub_value, structure))
      ret.extend(structure._to_tensor_list(sub_value))
    return ret

  def _from_tensor_list(self, flat_value):
    if len(flat_value) != len(self._flat_types):
      raise ValueError("Expected %d flat values in NestedStructure but got %d."
                       % (len(self._flat_types), len(flat_value)))

    flat_ret = []
    for sub_value, structure in zip(flat_value,
                                    nest.flatten(self._nested_structure)):
      flat_ret.append(structure._from_tensor_list([sub_value]))

    return nest.pack_sequence_as(self._nested_structure, flat_ret)

  @staticmethod
  def from_value(value):
    flat_nested_structure = [
        Structure.from_value(sub_value) for sub_value in nest.flatten(value)
    ]
    return NestedStructure(nest.pack_sequence_as(value, flat_nested_structure))


class TensorStructure(Structure):
  """Represents structural information about a `tf.Tensor`."""

  def __init__(self, dtype, shape):
    self._dtype = dtypes.as_dtype(dtype)
    self._shape = tensor_shape.as_shape(shape)

  @property
  def _flat_shapes(self):
    return [self._shape]

  @property
  def _flat_types(self):
    return [self._dtype]

  def is_compatible_with(self, other):
    return (isinstance(other, TensorStructure) and
            self._dtype.is_compatible_with(other._dtype) and
            self._shape.is_compatible_with(other._shape))

  def _to_tensor_list(self, value):
    if not self.is_compatible_with(Structure.from_value(value)):
      raise ValueError("Value %r is not convertible to a tensor with dtype %s "
                       "and shape %s." % (value, self._dtype, self._shape))
    return [value]

  def _from_tensor_list(self, flat_value):
    if len(flat_value) != 1:
      raise ValueError("TensorStructure corresponds to a single tf.Tensor.")
    if not self.is_compatible_with(Structure.from_value(flat_value[0])):
      raise ValueError("Cannot convert %r to a tensor with dtype %s and shape "
                       "%s." % (flat_value[0], self._dtype, self._shape))
    return flat_value[0]

  @staticmethod
  def from_value(value):
    return TensorStructure(value.dtype, value.shape)


class SparseTensorStructure(Structure):
  """Represents structural information about a `tf.SparseTensor`."""

  def __init__(self, dtype, dense_shape):
    self._dtype = dtypes.as_dtype(dtype)
    self._dense_shape = tensor_shape.as_shape(dense_shape)

  @property
  def _flat_shapes(self):
    return [tensor_shape.vector(3)]

  @property
  def _flat_types(self):
    return [dtypes.variant]

  def is_compatible_with(self, other):
    return (isinstance(other, SparseTensorStructure) and
            self._dtype.is_compatible_with(other._dtype) and
            self._dense_shape.is_compatible_with(other._dense_shape))

  def _to_tensor_list(self, value):
    return [sparse_ops.serialize_sparse(value, out_type=dtypes.variant)]

  def _from_tensor_list(self, flat_value):
    if (len(flat_value) != 1 or flat_value[0].dtype != dtypes.variant or
        not flat_value[0].shape.is_compatible_with(tensor_shape.vector(3))):
      raise ValueError("SparseTensorStructure corresponds to a single "
                       "tf.variant vector of length 3.")
    return sparse_ops.deserialize_sparse(
        flat_value[0], dtype=self._dtype, rank=self._dense_shape.ndims)

  @staticmethod
  def from_value(value):
    sparse_tensor = sparse_tensor_lib.SparseTensor.from_value(value)
    return SparseTensorStructure(
        sparse_tensor.dtype,
        tensor_util.constant_value_as_shape(sparse_tensor.dense_shape))

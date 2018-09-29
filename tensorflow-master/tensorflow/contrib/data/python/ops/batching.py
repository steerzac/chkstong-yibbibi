# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
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
"""Batching dataset transformations."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np

from tensorflow.contrib.data.python.ops import get_single_element
from tensorflow.contrib.data.python.ops import grouping
from tensorflow.contrib.framework import with_shape
from tensorflow.python.data.ops import dataset_ops
from tensorflow.python.data.util import convert
from tensorflow.python.data.util import nest
from tensorflow.python.data.util import sparse
from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import ops
from tensorflow.python.framework import sparse_tensor
from tensorflow.python.framework import tensor_shape
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import check_ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import gen_array_ops
from tensorflow.python.ops import gen_dataset_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import sparse_ops
from tensorflow.python.util import deprecation


def batch_window(dataset):
  """Batches a window of tensors.

  Args:
    dataset: the input dataset.

  Returns:
    A `Tensor` representing the batch of the entire input dataset.
  """
  if isinstance(dataset.output_classes, tuple):
    raise TypeError("Input dataset expected to have a single component")
  if dataset.output_classes is ops.Tensor:
    return _batch_dense_window(dataset)
  elif dataset.output_classes is sparse_tensor.SparseTensor:
    return _batch_sparse_window(dataset)
  else:
    raise TypeError("Unsupported dataset type: %s" % dataset.output_classes)


def _batch_dense_window(dataset):
  """Batches a window of dense tensors."""

  def key_fn(_):
    return np.int64(0)

  def shape_init_fn(_):
    return array_ops.shape(first_element)

  def shape_reduce_fn(state, value):
    check_ops.assert_equal(state, array_ops.shape(value))
    return state

  def finalize_fn(state):
    return state

  if dataset.output_shapes.is_fully_defined():
    shape = dataset.output_shapes
  else:
    first_element = get_single_element.get_single_element(dataset.take(1))
    shape_reducer = grouping.Reducer(shape_init_fn, shape_reduce_fn,
                                     finalize_fn)
    shape = get_single_element.get_single_element(
        dataset.apply(grouping.group_by_reducer(key_fn, shape_reducer)))

  def batch_init_fn(_):
    batch_shape = array_ops.concat([[0], shape], 0)
    return gen_array_ops.empty(batch_shape, dtype=dataset.output_types)

  def batch_reduce_fn(state, value):
    return array_ops.concat([state, [value]], 0)

  batch_reducer = grouping.Reducer(batch_init_fn, batch_reduce_fn, finalize_fn)
  return get_single_element.get_single_element(
      dataset.apply(grouping.group_by_reducer(key_fn, batch_reducer)))


def _batch_sparse_window(dataset):
  """Batches a window of sparse tensors."""

  def key_fn(_):
    return np.int64(0)

  def shape_init_fn(_):
    return first_element.dense_shape

  def shape_reduce_fn(state, value):
    check_ops.assert_equal(state, value.dense_shape)
    return state

  def finalize_fn(state):
    return state

  if dataset.output_shapes.is_fully_defined():
    shape = dataset.output_shapes
  else:
    first_element = get_single_element.get_single_element(dataset.take(1))
    shape_reducer = grouping.Reducer(shape_init_fn, shape_reduce_fn,
                                     finalize_fn)
    shape = get_single_element.get_single_element(
        dataset.apply(grouping.group_by_reducer(key_fn, shape_reducer)))

  def batch_init_fn(_):
    indices_shape = array_ops.concat([[0], [array_ops.size(shape) + 1]], 0)
    return sparse_tensor.SparseTensor(
        indices=gen_array_ops.empty(indices_shape, dtype=dtypes.int64),
        values=constant_op.constant([], shape=[0], dtype=dataset.output_types),
        dense_shape=array_ops.concat(
            [np.array([0], dtype=np.int64),
             math_ops.cast(shape, dtypes.int64)], 0))

  def batch_reduce_fn(state, value):
    return sparse_ops.sparse_concat(0, [state, value])

  def reshape_fn(value):
    return sparse_ops.sparse_reshape(
        value,
        array_ops.concat([np.array([1], dtype=np.int64), value.dense_shape], 0))

  batch_reducer = grouping.Reducer(batch_init_fn, batch_reduce_fn, finalize_fn)
  return get_single_element.get_single_element(
      dataset.map(reshape_fn).apply(
          grouping.group_by_reducer(key_fn, batch_reducer)))


def dense_to_sparse_batch(batch_size, row_shape):
  """A transformation that batches ragged elements into `tf.SparseTensor`s.

  Like `Dataset.padded_batch()`, this transformation combines multiple
  consecutive elements of the dataset, which might have different
  shapes, into a single element. The resulting element has three
  components (`indices`, `values`, and `dense_shape`), which
  comprise a `tf.SparseTensor` that represents the same data. The
  `row_shape` represents the dense shape of each row in the
  resulting `tf.SparseTensor`, to which the effective batch size is
  prepended. For example:

  ```python
  # NOTE: The following examples use `{ ... }` to represent the
  # contents of a dataset.
  a = { ['a', 'b', 'c'], ['a', 'b'], ['a', 'b', 'c', 'd'] }

  a.apply(tf.contrib.data.dense_to_sparse_batch(batch_size=2, row_shape=[6])) ==
  {
      ([[0, 0], [0, 1], [0, 2], [1, 0], [1, 1]],  # indices
       ['a', 'b', 'c', 'a', 'b'],                 # values
       [2, 6]),                                   # dense_shape
      ([[0, 0], [0, 1], [0, 2], [0, 3]],
       ['a', 'b', 'c', 'd'],
       [1, 6])
  }
  ```

  Args:
    batch_size: A `tf.int64` scalar `tf.Tensor`, representing the
      number of consecutive elements of this dataset to combine in a
      single batch.
    row_shape: A `tf.TensorShape` or `tf.int64` vector tensor-like
      object representing the equivalent dense shape of a row in the
      resulting `tf.SparseTensor`. Each element of this dataset must
      have the same rank as `row_shape`, and must have size less
      than or equal to `row_shape` in each dimension.

  Returns:
    A `Dataset` transformation function, which can be passed to
    `tf.data.Dataset.apply`.
  """

  def _apply_fn(dataset):
    return _DenseToSparseBatchDataset(dataset, batch_size, row_shape)

  return _apply_fn


def padded_batch_window(dataset, padded_shape, padding_value=None):
  """Batches a window of tensors with padding.

  Args:
    dataset: the input dataset.
    padded_shape: (Optional.) `tf.TensorShape` or `tf.int64` vector tensor-like
      object representing the shape to which the input elements should be padded
      prior to batching. Any unknown dimensions (e.g. `tf.Dimension(None)` in a
      `tf.TensorShape` or `-1` in a tensor-like object) will be padded to the
      maximum size of that dimension in each batch.
    padding_value: (Optional.) A scalar-shaped `tf.Tensor`, representing the
      padding value to use. Defaults are `0` for numeric types and the empty
      string for string types. If `dataset` contains `tf.SparseTensor`, this
      value is ignored.

  Returns:
    A `Tensor` representing the batch of the entire input dataset.

  Raises:
    ValueError: if invalid arguments are provided.
  """
  if not issubclass(dataset.output_classes,
                    (ops.Tensor, sparse_tensor.SparseTensor)):
    raise TypeError("Input dataset expected to have a single tensor component")
  if issubclass(dataset.output_classes, (ops.Tensor)):
    return _padded_batch_dense_window(dataset, padded_shape, padding_value)
  elif issubclass(dataset.output_classes, (sparse_tensor.SparseTensor)):
    if padding_value is not None:
      raise ValueError("Padding value not allowed for sparse tensors")
    return _padded_batch_sparse_window(dataset, padded_shape)
  else:
    raise TypeError("Unsupported dataset type: %s" % dataset.output_classes)


def _padded_batch_dense_window(dataset, padded_shape, padding_value=None):
  """Batches a window of dense tensors with padding."""

  padded_shape = math_ops.cast(
      convert.partial_shape_to_tensor(padded_shape), dtypes.int32)

  def key_fn(_):
    return np.int64(0)

  def max_init_fn(_):
    return padded_shape

  def max_reduce_fn(state, value):
    """Computes the maximum shape to pad to."""
    condition = math_ops.reduce_all(
        math_ops.logical_or(
            math_ops.less_equal(array_ops.shape(value), padded_shape),
            math_ops.equal(padded_shape, -1)))
    assert_op = control_flow_ops.Assert(condition, [
        "Actual shape greater than padded shape: ",
        array_ops.shape(value), padded_shape
    ])
    with ops.control_dependencies([assert_op]):
      return math_ops.maximum(state, array_ops.shape(value))

  def finalize_fn(state):
    return state

  # Compute the padded shape.
  max_reducer = grouping.Reducer(max_init_fn, max_reduce_fn, finalize_fn)
  padded_shape = get_single_element.get_single_element(
      dataset.apply(grouping.group_by_reducer(key_fn, max_reducer)))

  if padding_value is None:
    if dataset.output_types == dtypes.string:
      padding_value = ""
    elif dataset.output_types == dtypes.bool:
      padding_value = False
    elif dataset.output_types == dtypes.variant:
      raise TypeError("Unable to create padding for field of type 'variant'")
    else:
      padding_value = 0

  def batch_init_fn(_):
    batch_shape = array_ops.concat(
        [np.array([0], dtype=np.int32), padded_shape], 0)
    return gen_array_ops.empty(batch_shape, dtype=dataset.output_types)

  def batch_reduce_fn(state, value):
    return array_ops.concat([state, [value]], 0)

  def pad_fn(value):
    shape = array_ops.shape(value)
    left = array_ops.zeros_like(shape)
    right = padded_shape - shape
    return array_ops.pad(
        value, array_ops.stack([left, right], 1), constant_values=padding_value)

  batch_reducer = grouping.Reducer(batch_init_fn, batch_reduce_fn, finalize_fn)
  return get_single_element.get_single_element(
      dataset.map(pad_fn).apply(
          grouping.group_by_reducer(key_fn, batch_reducer)))


def _padded_batch_sparse_window(dataset, padded_shape):
  """Batches a window of sparse tensors with padding."""

  def key_fn(_):
    return np.int64(0)

  def max_init_fn(_):
    return convert.partial_shape_to_tensor(padded_shape)

  def max_reduce_fn(state, value):
    """Computes the maximum shape to pad to."""
    condition = math_ops.reduce_all(
        math_ops.logical_or(
            math_ops.less_equal(value.dense_shape, padded_shape),
            math_ops.equal(padded_shape, -1)))
    assert_op = control_flow_ops.Assert(condition, [
        "Actual shape greater than padded shape: ", value.dense_shape,
        padded_shape
    ])
    with ops.control_dependencies([assert_op]):
      return math_ops.maximum(state, value.dense_shape)

  def finalize_fn(state):
    return state

  # Compute the padded shape.
  max_reducer = grouping.Reducer(max_init_fn, max_reduce_fn, finalize_fn)
  padded_shape = get_single_element.get_single_element(
      dataset.apply(grouping.group_by_reducer(key_fn, max_reducer)))

  def batch_init_fn(_):
    indices_shape = array_ops.concat([[0], [array_ops.size(padded_shape) + 1]],
                                     0)
    return sparse_tensor.SparseTensor(
        indices=gen_array_ops.empty(indices_shape, dtype=dtypes.int64),
        values=constant_op.constant([], shape=[0], dtype=dataset.output_types),
        dense_shape=array_ops.concat(
            [np.array([0], dtype=np.int64), padded_shape], 0))

  def batch_reduce_fn(state, value):
    padded_value = sparse_tensor.SparseTensor(
        indices=value.indices, values=value.values, dense_shape=padded_shape)
    reshaped_value = sparse_ops.sparse_reshape(
        padded_value,
        array_ops.concat(
            [np.array([1], dtype=np.int64), padded_value.dense_shape], 0))
    return sparse_ops.sparse_concat(0, [state, reshaped_value])

  reducer = grouping.Reducer(batch_init_fn, batch_reduce_fn, finalize_fn)
  return get_single_element.get_single_element(
      dataset.apply(grouping.group_by_reducer(key_fn, reducer)))


class _UnbatchDataset(dataset_ops.UnaryDataset):
  """A dataset that splits the elements of its input into multiple elements."""

  def __init__(self, input_dataset):
    """See `unbatch()` for more details."""
    super(_UnbatchDataset, self).__init__(input_dataset)
    flat_shapes = nest.flatten(input_dataset.output_shapes)
    if any(s.ndims == 0 for s in flat_shapes):
      raise ValueError("Cannot unbatch an input with scalar components.")
    known_batch_dim = tensor_shape.Dimension(None)
    for s in flat_shapes:
      try:
        known_batch_dim = known_batch_dim.merge_with(s[0])
      except ValueError:
        raise ValueError("Cannot unbatch an input whose components have "
                         "different batch sizes.")
    self._input_dataset = input_dataset

  def _as_variant_tensor(self):
    return gen_dataset_ops.unbatch_dataset(
        self._input_dataset._as_variant_tensor(),  # pylint: disable=protected-access
        **dataset_ops.flat_structure(self))

  @property
  def output_classes(self):
    return self._input_dataset.output_classes

  @property
  def output_shapes(self):
    return nest.map_structure(lambda s: s[1:],
                              self._input_dataset.output_shapes)

  @property
  def output_types(self):
    return self._input_dataset.output_types


def unbatch():
  """Splits elements of a dataset into multiple elements on the batch dimension.

  For example, if elements of the dataset are shaped `[B, a0, a1, ...]`,
  where `B` may vary for each input element, then for each element in the
  dataset, the unbatched dataset will contain `B` consecutive elements
  of shape `[a0, a1, ...]`.

  ```python
  # NOTE: The following example uses `{ ... }` to represent the contents
  # of a dataset.
  a = { ['a', 'b', 'c'], ['a', 'b'], ['a', 'b', 'c', 'd'] }

  a.apply(tf.contrib.data.unbatch()) == {
      'a', 'b', 'c', 'a', 'b', 'a', 'b', 'c', 'd'}
  ```

  Returns:
    A `Dataset` transformation function, which can be passed to
    `tf.data.Dataset.apply`.
  """

  def _apply_fn(dataset):
    """Function from `Dataset` to `Dataset` that applies the transformation."""
    if not sparse.any_sparse(dataset.output_classes):
      return _UnbatchDataset(dataset)

    # NOTE(mrry): We must ensure that any SparseTensors in `dataset`
    # are normalized to the rank-1 dense representation, so that the
    # sparse-oblivious unbatching logic will slice them
    # appropriately. This leads to a somewhat inefficient re-encoding step
    # for all SparseTensor components.
    # TODO(mrry): Consider optimizing this in future
    # if it turns out to be a bottleneck.
    def normalize(arg, *rest):
      if rest:
        return sparse.serialize_many_sparse_tensors((arg,) + rest)
      else:
        return sparse.serialize_many_sparse_tensors(arg)

    normalized_dataset = dataset.map(normalize)

    # NOTE(mrry): Our `map()` has lost information about the sparseness
    # of any SparseTensor components, so re-apply the structure of the
    # original dataset.
    restructured_dataset = _RestructuredDataset(
        normalized_dataset,
        dataset.output_types,
        dataset.output_shapes,
        dataset.output_classes,
        allow_unsafe_cast=True)
    return _UnbatchDataset(restructured_dataset)

  return _apply_fn


@deprecation.deprecated(
    None, "Use `tf.data.Dataset.batch(..., drop_remainder=True)`.")
def batch_and_drop_remainder(batch_size):
  """A batching transformation that omits the final small batch (if present).

  Like `tf.data.Dataset.batch`, this transformation combines
  consecutive elements of this dataset into batches. However, if the batch
  size does not evenly divide the input dataset size, this transformation will
  drop the final smaller element.

  The following example illustrates the difference between this
  transformation and `Dataset.batch()`:

  ```python
  dataset = tf.data.Dataset.range(200)
  batched = dataset.apply(tf.contrib.data.batch_and_drop_remainder(128))
  print(batched.output_shapes)  # ==> "(128,)" (the batch dimension is known)
  ```

  By contrast, `dataset.batch(128)` would yield a two-element dataset with
  shapes `(128,)` and `(72,)`, so the batch dimension would not be statically
  known.

  Args:
    batch_size: A `tf.int64` scalar `tf.Tensor`, representing the number of
        consecutive elements of this dataset to combine in a single batch.

  Returns:
    A `Dataset` transformation function, which can be passed to
    `tf.data.Dataset.apply`
  """

  def _apply_fn(dataset):
    """Function from `Dataset` to `Dataset` that applies the transformation."""
    return dataset.batch(batch_size, drop_remainder=True)

  return _apply_fn


@deprecation.deprecated(
    None, "Use `tf.data.Dataset.padded_batch(..., drop_remainder=True)`.")
def padded_batch_and_drop_remainder(batch_size,
                                    padded_shapes,
                                    padding_values=None):
  """A batching and padding transformation that omits the final small batch.

  Like `tf.data.Dataset.padded_batch`, this transformation combines
  consecutive elements of this dataset into batches. However, if the batch
  size does not evenly divide the input dataset size, this transformation will
  drop the final smaller element.

  See `tf.contrib.data.batch_and_drop_remainder` for more details.

  Args:
    batch_size: A `tf.int64` scalar `tf.Tensor`, representing the number of
      consecutive elements of this dataset to combine in a single batch.
    padded_shapes: A nested structure of `tf.TensorShape` or
      `tf.int64` vector tensor-like objects. See
      `tf.data.Dataset.padded_batch` for details.
    padding_values: (Optional.) A nested structure of scalar-shaped
      `tf.Tensor`. See `tf.data.Dataset.padded_batch` for details.

  Returns:
    A `Dataset` transformation function, which can be passed to
    `tf.data.Dataset.apply`
  """

  def _apply_fn(dataset):
    """Function from `Dataset` to `Dataset` that applies the transformation."""
    return dataset.padded_batch(
        batch_size, padded_shapes=padded_shapes, padding_values=padding_values,
        drop_remainder=True)

  return _apply_fn


class _DenseToSparseBatchDataset(dataset_ops.UnaryDataset):
  """A `Dataset` that batches ragged dense elements into `tf.SparseTensor`s."""

  def __init__(self, input_dataset, batch_size, row_shape):
    """See `Dataset.dense_to_sparse_batch()` for more details."""
    super(_DenseToSparseBatchDataset, self).__init__(input_dataset)
    if not isinstance(input_dataset.output_types, dtypes.DType):
      raise TypeError("DenseToSparseDataset requires an input whose elements "
                      "have a single component, whereas the input has %r." %
                      input_dataset.output_types)
    self._input_dataset = input_dataset
    self._batch_size = batch_size
    self._row_shape = row_shape

  def _as_variant_tensor(self):
    return gen_dataset_ops.dense_to_sparse_batch_dataset(
        self._input_dataset._as_variant_tensor(),  # pylint: disable=protected-access
        self._batch_size,
        row_shape=convert.partial_shape_to_tensor(self._row_shape),
        **dataset_ops.flat_structure(self))

  @property
  def output_classes(self):
    return sparse_tensor.SparseTensor

  @property
  def output_shapes(self):
    return tensor_shape.vector(None).concatenate(self._row_shape)

  @property
  def output_types(self):
    return self._input_dataset.output_types


class _RestructuredDataset(dataset_ops.UnaryDataset):
  """An internal helper for changing the structure and shape of a dataset."""

  def __init__(self,
               dataset,
               output_types,
               output_shapes=None,
               output_classes=None,
               allow_unsafe_cast=False):
    """Creates a new dataset with the given output types and shapes.

    The given `dataset` must have a structure that is convertible:
    * `dataset.output_types` must be the same as `output_types` module nesting.
    * Each shape in `dataset.output_shapes` must be compatible with each shape
      in `output_shapes` (if given).

    Note: This helper permits "unsafe casts" for shapes, equivalent to using
    `tf.Tensor.set_shape()` where domain-specific knowledge is available.

    Args:
      dataset: A `Dataset` object.
      output_types: A nested structure of `tf.DType` objects.
      output_shapes: (Optional.) A nested structure of `tf.TensorShape` objects.
        If omitted, the shapes will be inherited from `dataset`.
      output_classes: (Optional.) A nested structure of class types.
        If omitted, the class types will be inherited from `dataset`.
      allow_unsafe_cast: (Optional.) If `True`, the caller may switch the
        reported output types and shapes of the restructured dataset, e.g. to
        switch a sparse tensor represented as `tf.variant` to its user-visible
        type and shape.

    Raises:
      ValueError: If either `output_types` or `output_shapes` is not compatible
        with the structure of `dataset`.
    """
    super(_RestructuredDataset, self).__init__(dataset)
    self._input_dataset = dataset

    if not allow_unsafe_cast:
      # Validate that the types are compatible.
      output_types = nest.map_structure(dtypes.as_dtype, output_types)
      flat_original_types = nest.flatten(dataset.output_types)
      flat_new_types = nest.flatten(output_types)
      if flat_original_types != flat_new_types:
        raise ValueError(
            "Dataset with output types %r cannot be restructured to have "
            "output types %r" % (dataset.output_types, output_types))

    self._output_types = output_types

    if output_shapes is None:
      # Inherit shapes from the original `dataset`.
      self._output_shapes = nest.pack_sequence_as(output_types,
                                                  nest.flatten(
                                                      dataset.output_shapes))
    else:
      if not allow_unsafe_cast:
        # Validate that the shapes are compatible.
        nest.assert_same_structure(output_types, output_shapes)
        flat_original_shapes = nest.flatten(dataset.output_shapes)
        flat_new_shapes = nest.flatten_up_to(output_types, output_shapes)

        for original_shape, new_shape in zip(flat_original_shapes,
                                             flat_new_shapes):
          if not original_shape.is_compatible_with(new_shape):
            raise ValueError(
                "Dataset with output shapes %r cannot be restructured to have "
                "incompatible output shapes %r" % (dataset.output_shapes,
                                                   output_shapes))
      self._output_shapes = nest.map_structure_up_to(
          output_types, tensor_shape.as_shape, output_shapes)
    if output_classes is None:
      # Inherit class types from the original `dataset`.
      self._output_classes = nest.pack_sequence_as(output_types,
                                                   nest.flatten(
                                                       dataset.output_classes))
    else:
      self._output_classes = output_classes

  def _as_variant_tensor(self):
    return self._input_dataset._as_variant_tensor()  # pylint: disable=protected-access

  @property
  def output_classes(self):
    return self._output_classes

  @property
  def output_types(self):
    return self._output_types

  @property
  def output_shapes(self):
    return self._output_shapes


def assert_element_shape(expected_shapes):
  """Assert the shape of this `Dataset`.

  ```python
  shapes = [tf.TensorShape([16, 256]), tf.TensorShape([None, 2])]
  result = dataset.apply(tf.contrib.data.assert_element_shape(shapes))
  print(result.output_shapes)  # ==> "((16, 256), (<unknown>, 2))"
  ```

  If dataset shapes and expected_shape, are fully defined, assert they match.
  Otherwise, add assert op that will validate the shapes when tensors are
  evaluated, and set shapes on tensors, respectively.

  Note that unknown dimension in `expected_shapes` will be ignored.

  Args:
    expected_shapes: A nested structure of `tf.TensorShape` objects.

  Returns:
    A `Dataset` transformation function, which can be passed to
    `tf.data.Dataset.apply`
  """

  def _merge_output_shapes(original_shapes, expected_shapes):
    flat_original_shapes = nest.flatten(original_shapes)
    flat_new_shapes = nest.flatten_up_to(original_shapes, expected_shapes)
    flat_merged_output_shapes = [
        original_shape.merge_with(new_shape)
        for original_shape, new_shape in zip(flat_original_shapes,
                                             flat_new_shapes)]
    return nest.pack_sequence_as(original_shapes, flat_merged_output_shapes)

  def _check_shape(*elements):
    flatten_tensors = nest.flatten(elements)
    flatten_shapes = nest.flatten(expected_shapes)
    checked_tensors = [
        with_shape(shape, tensor) if shape else tensor  # Ignore unknown shape
        for shape, tensor in zip(flatten_shapes, flatten_tensors)
    ]
    return nest.pack_sequence_as(elements, checked_tensors)

  def _apply_fn(dataset):
    output_shapes = _merge_output_shapes(dataset.output_shapes,
                                         expected_shapes)
    return _RestructuredDataset(
        dataset.map(_check_shape),
        dataset.output_types,
        output_shapes=output_shapes,
        output_classes=dataset.output_classes)

  return _apply_fn


class _MapAndBatchDataset(dataset_ops.MapDataset):
  """A `Dataset` that maps a function over a batch of elements."""

  def __init__(self, input_dataset, map_func, batch_size, num_parallel_calls,
               drop_remainder):
    """See `Dataset.map()` for details."""
    super(_MapAndBatchDataset, self).__init__(input_dataset, map_func)
    self._batch_size_t = ops.convert_to_tensor(
        batch_size, dtype=dtypes.int64, name="batch_size")
    self._num_parallel_calls_t = ops.convert_to_tensor(
        num_parallel_calls, dtype=dtypes.int64, name="num_parallel_calls")
    self._drop_remainder_t = ops.convert_to_tensor(
        drop_remainder, dtype=dtypes.bool, name="drop_remainder")

    self._batch_size = batch_size
    self._drop_remainder = drop_remainder

  def _as_variant_tensor(self):
    # pylint: disable=protected-access
    input_resource = self._input_dataset._as_variant_tensor()
    return gen_dataset_ops.map_and_batch_dataset_v2(
        input_resource,
        self._map_func.captured_inputs,
        f=self._map_func,
        batch_size=self._batch_size_t,
        num_parallel_calls=self._num_parallel_calls_t,
        drop_remainder=self._drop_remainder_t,
        **dataset_ops.flat_structure(self))
    # pylint: enable=protected-access

  @property
  def output_shapes(self):
    dim = self._batch_size if self._drop_remainder else None
    return nest.pack_sequence_as(self._output_shapes, [
        tensor_shape.vector(dim).concatenate(s)
        for s in nest.flatten(self._output_shapes)
    ])

  @property
  def output_types(self):
    return self._output_types


def map_and_batch(map_func,
                  batch_size,
                  num_parallel_batches=None,
                  drop_remainder=False,
                  num_parallel_calls=None):
  """Fused implementation of `map` and `batch`.

  Maps `map_func` across `batch_size` consecutive elements of this dataset
  and then combines them into a batch. Functionally, it is equivalent to `map`
  followed by `batch`. However, by fusing the two transformations together, the
  implementation can be more efficient. Surfacing this transformation in the API
  is temporary. Once automatic input pipeline optimization is implemented,
  the fusing of `map` and `batch` will happen automatically and this API will be
  deprecated.

  Args:
    map_func: A function mapping a nested structure of tensors to another
      nested structure of tensors.
    batch_size: A `tf.int64` scalar `tf.Tensor`, representing the number of
      consecutive elements of this dataset to combine in a single batch.
    num_parallel_batches: (Optional.) A `tf.int64` scalar `tf.Tensor`,
      representing the number of batches to create in parallel. On one hand,
      higher values can help mitigate the effect of stragglers. On the other
      hand, higher values can increase contention if CPU is scarce.
    drop_remainder: (Optional.) A `tf.bool` scalar `tf.Tensor`, representing
      whether the last batch should be dropped in case its size is smaller than
      desired; the default behavior is not to drop the smaller batch.
    num_parallel_calls: (Optional.) A `tf.int32` scalar `tf.Tensor`,
        representing the number of elements to process in parallel. If not
        specified, `batch_size * num_parallel_batches` elements will be
        processed in parallel.

  Returns:
    A `Dataset` transformation function, which can be passed to
    `tf.data.Dataset.apply`.

  Raises:
    ValueError: If both `num_parallel_batches` and `num_parallel_calls` are
      specified.
  """

  if num_parallel_batches is None and num_parallel_calls is None:
    num_parallel_calls = batch_size
  elif num_parallel_batches is not None and num_parallel_calls is None:
    num_parallel_calls = batch_size * num_parallel_batches
  elif num_parallel_batches is not None and num_parallel_calls is not None:
    raise ValueError("The `num_parallel_batches` and `num_parallel_calls` "
                     "arguments are mutually exclusive.")

  def _apply_fn(dataset):
    return _MapAndBatchDataset(dataset, map_func, batch_size,
                               num_parallel_calls, drop_remainder)

  return _apply_fn

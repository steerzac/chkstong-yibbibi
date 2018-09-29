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
"""Python wrapper for prefetching_ops."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from tensorflow.python.data.ops import dataset_ops
from tensorflow.python.data.util import nest
from tensorflow.python.data.util import sparse
from tensorflow.python.eager import context
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import function
from tensorflow.python.framework import ops
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import functional_ops
from tensorflow.python.ops import gen_dataset_ops


class _PerDeviceGenerator(dataset_ops.Dataset):
  """A `dummy` generator dataset."""

  def __init__(self, shard_num, multi_device_iterator_resource, incarnation_id,
               source_device, target_device, output_shapes, output_types,
               output_classes):
    self._target_device = target_device
    self._output_types = output_types
    self._output_shapes = output_shapes
    self._output_classes = output_classes
    self._flat_output_shapes = nest.flatten(
        sparse.as_dense_shapes(self._output_shapes, self._output_classes))
    self._flat_output_types = nest.flatten(
        sparse.as_dense_types(self._output_types, self._output_classes))

    multi_device_iterator_string_handle = (
        gen_dataset_ops.multi_device_iterator_to_string_handle(
            multi_device_iterator_resource))

    @function.Defun()
    def _init_func():
      return multi_device_iterator_string_handle

    @function.Defun()
    def _remote_init_func():
      return functional_ops.remote_call(
          target=source_device,
          args=_init_func.captured_inputs,
          Tout=[dtypes.string],
          f=_init_func)

    self._init_func = _remote_init_func
    self._init_captured_args = _remote_init_func.captured_inputs

    @function.Defun(dtypes.string)
    def _next_func(string_handle):
      multi_device_iterator = (
          gen_dataset_ops.multi_device_iterator_from_string_handle(
              string_handle=string_handle,
              output_types=self._flat_output_types,
              output_shapes=self._flat_output_shapes))
      return gen_dataset_ops.multi_device_iterator_get_next_from_shard(
          multi_device_iterator=multi_device_iterator,
          shard_num=shard_num,
          incarnation_id=incarnation_id,
          output_types=self._flat_output_types,
          output_shapes=self._flat_output_shapes)

    @function.Defun(dtypes.string)
    def _remote_next_func(string_handle):
      return functional_ops.remote_call(
          target=source_device,
          args=[string_handle] + _next_func.captured_inputs,
          Tout=self._flat_output_types,
          f=_next_func)

    self._next_func = _remote_next_func
    self._next_captured_args = _remote_next_func.captured_inputs

    @function.Defun(dtypes.string)
    def _finalize_func(unused_string_handle):
      return array_ops.constant(0, dtypes.int64)

    @function.Defun(dtypes.string)
    def _remote_finalize_func(string_handle):
      return functional_ops.remote_call(
          target=source_device,
          args=[string_handle] + _finalize_func.captured_inputs,
          Tout=[dtypes.int64],
          f=_finalize_func)

    self._finalize_func = _remote_finalize_func
    self._finalize_captured_args = _remote_finalize_func.captured_inputs

  def _as_variant_tensor(self):
    with ops.device(self._target_device):
      return gen_dataset_ops.generator_dataset(
          self._init_captured_args,
          self._next_captured_args,
          self._finalize_captured_args,
          init_func=self._init_func,
          next_func=self._next_func,
          finalize_func=self._finalize_func,
          output_types=self._flat_output_types,
          output_shapes=self._flat_output_shapes)

  def _inputs(self):
    # TODO(b/116506223): Determine which datasets should be used as inputs here.
    return []

  @property
  def output_types(self):
    return self._output_types

  @property
  def output_shapes(self):
    return self._output_shapes

  @property
  def output_classes(self):
    return self._output_classes


class MultiDeviceIterator(object):
  """An iterator over multiple devices.

  @compatibility(eager)
  MultiDeviceIterator isn't currently supported in Eager mode but support is
  coming soon.
  @end_compatibility
  """

  def __init__(self,
               dataset,
               devices,
               max_buffer_size=1,
               prefetch_buffer_size=1,
               source_device="/cpu:0"):
    """Constructs a MultiDeviceIterator.

    Args:
      dataset: The input dataset to be iterated over.
      devices: The list of devices to fetch data to.
      max_buffer_size: Maximum size of the host side per device buffer to keep.
      prefetch_buffer_size: if > 1, then we setup a buffer on each device
        to prefetch into.
      source_device: The host device to place the `dataset` on.

    Raises:
      RuntimeError: If run in Eager mode.
    """
    if context.executing_eagerly():
      # TODO(rohanj): Fix this. Tracking bug: b/116467184
      raise RuntimeError("MultiDeviceIterator is not currently supported in "
                         "Eager mode.")
    self._dataset = dataset
    self._devices = devices
    self._source_device = source_device
    self._source_device_tensor = ops.convert_to_tensor(source_device)

    self._flat_output_shapes = nest.flatten(
        sparse.as_dense_shapes(self._dataset.output_shapes,
                               self._dataset.output_classes))
    self._flat_output_types = nest.flatten(
        sparse.as_dense_types(self._dataset.output_types,
                              self._dataset.output_classes))

    # Create the MultiDeviceIterator.
    with ops.device(self._source_device):
      self._multi_device_iterator_resource = (
          gen_dataset_ops.multi_device_iterator(
              devices=self._devices,
              shared_name="",
              container="",
              output_types=self._flat_output_types,
              output_shapes=self._flat_output_shapes))

      # The incarnation ID is used to ensure consistency between the per-device
      # iterators and the multi-device iterator.
      self._incarnation_id = gen_dataset_ops.multi_device_iterator_init(
          self._dataset._as_variant_tensor(),  # pylint: disable=protected-access
          self._multi_device_iterator_resource,
          max_buffer_size=max_buffer_size)

    # TODO(rohanj): Explore the possibility of the MultiDeviceIterator to
    # initialize the device side of the pipeline. This would allow the
    # MultiDeviceIterator to choose, for example, to move some transformations
    # into the device side from its input. It might be useful in rewriting.
    # Create the per device iterators.
    self._device_iterators = []
    i = 0
    for device in self._devices:
      ds = _PerDeviceGenerator(
          i, self._multi_device_iterator_resource, self._incarnation_id,
          self._source_device_tensor, device, self._dataset.output_shapes,
          self._dataset.output_types, self._dataset.output_classes)
      if prefetch_buffer_size > 0:
        ds = ds.prefetch(prefetch_buffer_size)
      with ops.device(device):
        self._device_iterators.append(ds.make_initializable_iterator())
      i += 1

    device_iterator_initializers = [
        iterator.initializer for iterator in self._device_iterators
    ]
    self._initializer = control_flow_ops.group(*device_iterator_initializers)

  def get_next(self):
    result = []
    i = 0
    for device in self._devices:
      with ops.device(device):
        result.append(self._device_iterators[i].get_next())
      i += 1
    return result

  @property
  def initializer(self):
    return self._initializer

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
"""Tests for the experimental input pipeline ops."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import random

import numpy as np

from tensorflow.contrib.data.python.ops import grouping
from tensorflow.python.data.kernel_tests import test_base
from tensorflow.python.data.ops import dataset_ops
from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import errors
from tensorflow.python.framework import ops
from tensorflow.python.framework import sparse_tensor
from tensorflow.python.framework import tensor_shape
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import string_ops
from tensorflow.python.platform import test


class GroupByReducerTest(test_base.DatasetTestBase):

  def checkResults(self, dataset, shapes, values):
    self.assertEqual(shapes, dataset.output_shapes)
    get_next = dataset.make_one_shot_iterator().get_next()
    with self.cached_session() as sess:
      for expected in values:
        got = sess.run(get_next)
        self.assertEqual(got, expected)
      with self.assertRaises(errors.OutOfRangeError):
        sess.run(get_next)

  def testSum(self):
    reducer = grouping.Reducer(
        init_func=lambda _: np.int64(0),
        reduce_func=lambda x, y: x + y,
        finalize_func=lambda x: x)
    for i in range(1, 11):
      dataset = dataset_ops.Dataset.range(2 * i).apply(
          grouping.group_by_reducer(lambda x: x % 2, reducer))
      self.checkResults(
          dataset, shapes=tensor_shape.scalar(), values=[(i - 1) * i, i * i])

  def testAverage(self):

    def reduce_fn(x, y):
      return (x[0] * x[1] + math_ops.cast(y, dtypes.float32)) / (
          x[1] + 1), x[1] + 1

    reducer = grouping.Reducer(
        init_func=lambda _: (0.0, 0.0),
        reduce_func=reduce_fn,
        finalize_func=lambda x, _: x)
    for i in range(1, 11):
      dataset = dataset_ops.Dataset.range(2 * i).apply(
          grouping.group_by_reducer(
              lambda x: math_ops.cast(x, dtypes.int64) % 2, reducer))
      self.checkResults(
          dataset, shapes=tensor_shape.scalar(), values=[i - 1, i])

  def testConcat(self):
    components = np.array(list("abcdefghijklmnopqrst")).view(np.chararray)
    reducer = grouping.Reducer(
        init_func=lambda x: "",
        reduce_func=lambda x, y: x + y[0],
        finalize_func=lambda x: x)
    for i in range(1, 11):
      dataset = dataset_ops.Dataset.zip(
          (dataset_ops.Dataset.from_tensor_slices(components),
           dataset_ops.Dataset.range(2 * i))).apply(
               grouping.group_by_reducer(lambda x, y: y % 2, reducer))
      self.checkResults(
          dataset,
          shapes=tensor_shape.scalar(),
          values=[b"acegikmoqs" [:i], b"bdfhjlnprt" [:i]])

  def testSparseSum(self):
    def _sparse(i):
      return sparse_tensor.SparseTensorValue(
          indices=np.array([[0, 0]]),
          values=(i * np.array([1], dtype=np.int64)),
          dense_shape=np.array([1, 1]))

    reducer = grouping.Reducer(
        init_func=lambda _: _sparse(np.int64(0)),
        reduce_func=lambda x, y: _sparse(x.values[0] + y.values[0]),
        finalize_func=lambda x: x.values[0])
    for i in range(1, 11):
      dataset = dataset_ops.Dataset.range(2 * i).map(_sparse).apply(
          grouping.group_by_reducer(lambda x: x.values[0] % 2, reducer))
      self.checkResults(
          dataset, shapes=tensor_shape.scalar(), values=[(i - 1) * i, i * i])

  def testChangingStateShape(self):

    def reduce_fn(x, _):
      # Statically known rank, but dynamic length.
      larger_dim = array_ops.concat([x[0], x[0]], 0)
      # Statically unknown rank.
      larger_rank = array_ops.expand_dims(x[1], 0)
      return larger_dim, larger_rank

    reducer = grouping.Reducer(
        init_func=lambda x: ([0], 1),
        reduce_func=reduce_fn,
        finalize_func=lambda x, y: (x, y))

    for i in range(1, 11):
      dataset = dataset_ops.Dataset.from_tensors(np.int64(0)).repeat(i).apply(
          grouping.group_by_reducer(lambda x: x, reducer))
      self.assertEqual([None], dataset.output_shapes[0].as_list())
      self.assertIs(None, dataset.output_shapes[1].ndims)
      iterator = dataset.make_one_shot_iterator()
      get_next = iterator.get_next()
      with self.cached_session() as sess:
        x, y = sess.run(get_next)
        self.assertAllEqual([0] * (2**i), x)
        self.assertAllEqual(np.array(1, ndmin=i), y)
        with self.assertRaises(errors.OutOfRangeError):
          sess.run(get_next)

  def testTypeMismatch(self):
    reducer = grouping.Reducer(
        init_func=lambda x: constant_op.constant(1, dtype=dtypes.int32),
        reduce_func=lambda x, y: constant_op.constant(1, dtype=dtypes.int64),
        finalize_func=lambda x: x)

    dataset = dataset_ops.Dataset.range(10)
    with self.assertRaisesRegexp(
        TypeError,
        "The element types for the new state must match the initial state."):
      dataset.apply(
          grouping.group_by_reducer(lambda _: np.int64(0), reducer))

  # TODO(b/78665031): Remove once non-scalar keys are supported.
  def testInvalidKeyShape(self):
    reducer = grouping.Reducer(
        init_func=lambda x: np.int64(0),
        reduce_func=lambda x, y: x + y,
        finalize_func=lambda x: x)

    dataset = dataset_ops.Dataset.range(10)
    with self.assertRaisesRegexp(
        ValueError, "`key_func` must return a single tf.int64 tensor."):
      dataset.apply(
          grouping.group_by_reducer(lambda _: np.int64((0, 0)), reducer))

  # TODO(b/78665031): Remove once non-int64 keys are supported.
  def testInvalidKeyType(self):
    reducer = grouping.Reducer(
        init_func=lambda x: np.int64(0),
        reduce_func=lambda x, y: x + y,
        finalize_func=lambda x: x)

    dataset = dataset_ops.Dataset.range(10)
    with self.assertRaisesRegexp(
        ValueError, "`key_func` must return a single tf.int64 tensor."):
      dataset.apply(
          grouping.group_by_reducer(lambda _: "wrong", reducer))

  def testTuple(self):
    def init_fn(_):
      return np.array([], dtype=np.int64), np.int64(0)

    def reduce_fn(state, value):
      s1, s2 = state
      v1, v2 = value
      return array_ops.concat([s1, [v1]], 0), s2 + v2

    def finalize_fn(s1, s2):
      return s1, s2

    reducer = grouping.Reducer(init_fn, reduce_fn, finalize_fn)
    dataset = dataset_ops.Dataset.zip(
        (dataset_ops.Dataset.range(10), dataset_ops.Dataset.range(10))).apply(
            grouping.group_by_reducer(lambda x, y: np.int64(0), reducer))
    get_next = dataset.make_one_shot_iterator().get_next()
    with self.cached_session() as sess:
      x, y = sess.run(get_next)
      self.assertAllEqual(x, np.asarray([x for x in range(10)]))
      self.assertEqual(y, 45)


class GroupByWindowTest(test_base.DatasetTestBase):

  def testSimple(self):
    components = np.random.randint(100, size=(200,)).astype(np.int64)
    iterator = (
        dataset_ops.Dataset.from_tensor_slices(components).map(lambda x: x * x)
        .apply(
            grouping.group_by_window(lambda x: x % 2, lambda _, xs: xs.batch(4),
                                     4)).make_initializable_iterator())
    init_op = iterator.initializer
    get_next = iterator.get_next()

    with self.cached_session() as sess:
      sess.run(init_op)
      counts = []
      with self.assertRaises(errors.OutOfRangeError):
        while True:
          result = sess.run(get_next)
          self.assertTrue(
              all(x % 2 == 0
                  for x in result) or all(x % 2 == 1)
              for x in result)
          counts.append(result.shape[0])

      self.assertEqual(len(components), sum(counts))
      num_full_batches = len([c for c in counts if c == 4])
      self.assertGreaterEqual(num_full_batches, 24)
      self.assertTrue(all(c == 4 for c in counts[:num_full_batches]))

  def testImmediateOutput(self):
    components = np.array(
        [0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 0, 0, 2, 2, 0, 0], dtype=np.int64)
    iterator = (
        dataset_ops.Dataset.from_tensor_slices(components).repeat(-1).apply(
            grouping.group_by_window(lambda x: x % 3, lambda _, xs: xs.batch(4),
                                     4)).make_initializable_iterator())
    init_op = iterator.initializer
    get_next = iterator.get_next()

    with self.cached_session() as sess:
      sess.run(init_op)
      # The input is infinite, so this test demonstrates that:
      # 1. We produce output without having to consume the entire input,
      # 2. Different buckets can produce output at different rates, and
      # 3. For deterministic input, the output is deterministic.
      for _ in range(3):
        self.assertAllEqual([0, 0, 0, 0], sess.run(get_next))
        self.assertAllEqual([1, 1, 1, 1], sess.run(get_next))
        self.assertAllEqual([2, 2, 2, 2], sess.run(get_next))
        self.assertAllEqual([0, 0, 0, 0], sess.run(get_next))

  def testSmallGroups(self):
    components = np.array([0, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0], dtype=np.int64)
    iterator = (
        dataset_ops.Dataset.from_tensor_slices(components).apply(
            grouping.group_by_window(lambda x: x % 2, lambda _, xs: xs.batch(4),
                                     4)).make_initializable_iterator())
    init_op = iterator.initializer
    get_next = iterator.get_next()

    with self.cached_session() as sess:
      sess.run(init_op)
      self.assertAllEqual([0, 0, 0, 0], sess.run(get_next))
      self.assertAllEqual([1, 1, 1, 1], sess.run(get_next))
      # The small outputs at the end are deterministically produced in key
      # order.
      self.assertAllEqual([0, 0, 0], sess.run(get_next))
      self.assertAllEqual([1], sess.run(get_next))

  def testEmpty(self):
    iterator = (
        dataset_ops.Dataset.range(4).apply(
            grouping.group_by_window(lambda _: 0, lambda _, xs: xs, 0))
        .make_initializable_iterator())
    init_op = iterator.initializer
    get_next = iterator.get_next()

    with self.cached_session() as sess:
      sess.run(init_op)
      with self.assertRaisesRegexp(
          errors.InvalidArgumentError,
          "Window size must be greater than zero, but got 0."):
        print(sess.run(get_next))

  def testReduceFuncError(self):
    components = np.random.randint(100, size=(200,)).astype(np.int64)

    def reduce_func(_, xs):
      # Introduce an incorrect padded shape that cannot (currently) be
      # detected at graph construction time.
      return xs.padded_batch(
          4,
          padded_shapes=(tensor_shape.TensorShape([]),
                         constant_op.constant([5], dtype=dtypes.int64) * -1))

    iterator = (
        dataset_ops.Dataset.from_tensor_slices(components)
        .map(lambda x: (x, ops.convert_to_tensor([x * x]))).apply(
            grouping.group_by_window(lambda x, _: x % 2, reduce_func,
                                     32)).make_initializable_iterator())
    init_op = iterator.initializer
    get_next = iterator.get_next()

    with self.cached_session() as sess:
      sess.run(init_op)
      with self.assertRaises(errors.InvalidArgumentError):
        sess.run(get_next)

  def testConsumeWindowDatasetMoreThanOnce(self):
    components = np.random.randint(50, size=(200,)).astype(np.int64)

    def reduce_func(key, window):
      # Apply two different kinds of padding to the input: tight
      # padding, and quantized (to a multiple of 10) padding.
      return dataset_ops.Dataset.zip((
          window.padded_batch(
              4, padded_shapes=tensor_shape.TensorShape([None])),
          window.padded_batch(
              4, padded_shapes=ops.convert_to_tensor([(key + 1) * 10])),
      ))

    iterator = (
        dataset_ops.Dataset.from_tensor_slices(components)
        .map(lambda x: array_ops.fill([math_ops.cast(x, dtypes.int32)], x))
        .apply(grouping.group_by_window(
            lambda x: math_ops.cast(array_ops.shape(x)[0] // 10, dtypes.int64),
            reduce_func, 4))
        .make_initializable_iterator())
    init_op = iterator.initializer
    get_next = iterator.get_next()

    with self.cached_session() as sess:
      sess.run(init_op)
      counts = []
      with self.assertRaises(errors.OutOfRangeError):
        while True:
          tight_result, multiple_of_10_result = sess.run(get_next)
          self.assertEqual(0, multiple_of_10_result.shape[1] % 10)
          self.assertAllEqual(tight_result,
                              multiple_of_10_result[:, :tight_result.shape[1]])
          counts.append(tight_result.shape[0])
      self.assertEqual(len(components), sum(counts))


# NOTE(mrry): These tests are based on the tests in bucket_ops_test.py.
# Currently, they use a constant batch size, though should be made to use a
# different batch size per key.
class BucketTest(test_base.DatasetTestBase):

  def _dynamicPad(self, bucket, window, window_size):
    # TODO(mrry): To match `tf.contrib.training.bucket()`, implement a
    # generic form of padded_batch that pads every component
    # dynamically and does not rely on static shape information about
    # the arguments.
    return dataset_ops.Dataset.zip(
        (dataset_ops.Dataset.from_tensors(bucket),
         window.padded_batch(
             32, (tensor_shape.TensorShape([]), tensor_shape.TensorShape(
                 [None]), tensor_shape.TensorShape([3])))))

  def testSingleBucket(self):

    def _map_fn(v):
      return (v, array_ops.fill([v], v),
              array_ops.fill([3], string_ops.as_string(v)))

    input_dataset = (
        dataset_ops.Dataset.from_tensor_slices(math_ops.range(32)).map(_map_fn))

    bucketed_dataset = input_dataset.apply(
        grouping.group_by_window(
            lambda x, y, z: 0,
            lambda k, bucket: self._dynamicPad(k, bucket, 32), 32))

    iterator = bucketed_dataset.make_initializable_iterator()
    init_op = iterator.initializer
    get_next = iterator.get_next()

    with self.cached_session() as sess:
      sess.run(init_op)

      which_bucket, bucketed_values = sess.run(get_next)

      self.assertEqual(0, which_bucket)

      expected_scalar_int = np.arange(32, dtype=np.int64)
      expected_unk_int64 = np.zeros((32, 31)).astype(np.int64)
      for i in range(32):
        expected_unk_int64[i, :i] = i
      expected_vec3_str = np.vstack(3 * [np.arange(32).astype(bytes)]).T

      self.assertAllEqual(expected_scalar_int, bucketed_values[0])
      self.assertAllEqual(expected_unk_int64, bucketed_values[1])
      self.assertAllEqual(expected_vec3_str, bucketed_values[2])

  def testEvenOddBuckets(self):

    def _map_fn(v):
      return (v, array_ops.fill([v], v),
              array_ops.fill([3], string_ops.as_string(v)))

    input_dataset = (
        dataset_ops.Dataset.from_tensor_slices(math_ops.range(64)).map(_map_fn))

    bucketed_dataset = input_dataset.apply(
        grouping.group_by_window(
            lambda x, y, z: math_ops.cast(x % 2, dtypes.int64),
            lambda k, bucket: self._dynamicPad(k, bucket, 32), 32))

    iterator = bucketed_dataset.make_initializable_iterator()
    init_op = iterator.initializer
    get_next = iterator.get_next()

    with self.cached_session() as sess:
      sess.run(init_op)

      # Get two minibatches (one containing even values, one containing odds)
      which_bucket_even, bucketed_values_even = sess.run(get_next)
      which_bucket_odd, bucketed_values_odd = sess.run(get_next)

      # Count number of bucket_tensors.
      self.assertEqual(3, len(bucketed_values_even))
      self.assertEqual(3, len(bucketed_values_odd))

      # Ensure bucket 0 was used for all minibatch entries.
      self.assertAllEqual(0, which_bucket_even)
      self.assertAllEqual(1, which_bucket_odd)

      # Test the first bucket outputted, the events starting at 0
      expected_scalar_int = np.arange(0, 32 * 2, 2, dtype=np.int64)
      expected_unk_int64 = np.zeros((32, 31 * 2)).astype(np.int64)
      for i in range(0, 32):
        expected_unk_int64[i, :2 * i] = 2 * i
        expected_vec3_str = np.vstack(
            3 * [np.arange(0, 32 * 2, 2).astype(bytes)]).T

      self.assertAllEqual(expected_scalar_int, bucketed_values_even[0])
      self.assertAllEqual(expected_unk_int64, bucketed_values_even[1])
      self.assertAllEqual(expected_vec3_str, bucketed_values_even[2])

      # Test the second bucket outputted, the odds starting at 1
      expected_scalar_int = np.arange(1, 32 * 2 + 1, 2, dtype=np.int64)
      expected_unk_int64 = np.zeros((32, 31 * 2 + 1)).astype(np.int64)
      for i in range(0, 32):
        expected_unk_int64[i, :2 * i + 1] = 2 * i + 1
        expected_vec3_str = np.vstack(
            3 * [np.arange(1, 32 * 2 + 1, 2).astype(bytes)]).T

      self.assertAllEqual(expected_scalar_int, bucketed_values_odd[0])
      self.assertAllEqual(expected_unk_int64, bucketed_values_odd[1])
      self.assertAllEqual(expected_vec3_str, bucketed_values_odd[2])

  def testEvenOddBucketsFilterOutAllOdd(self):

    def _map_fn(v):
      return {
          "x": v,
          "y": array_ops.fill([v], v),
          "z": array_ops.fill([3], string_ops.as_string(v))
      }

    def _dynamic_pad_fn(bucket, window, _):
      return dataset_ops.Dataset.zip(
          (dataset_ops.Dataset.from_tensors(bucket),
           window.padded_batch(
               32, {
                   "x": tensor_shape.TensorShape([]),
                   "y": tensor_shape.TensorShape([None]),
                   "z": tensor_shape.TensorShape([3])
               })))

    input_dataset = (
        dataset_ops.Dataset.from_tensor_slices(math_ops.range(128)).map(_map_fn)
        .filter(lambda d: math_ops.equal(d["x"] % 2, 0)))

    bucketed_dataset = input_dataset.apply(
        grouping.group_by_window(
            lambda d: math_ops.cast(d["x"] % 2, dtypes.int64),
            lambda k, bucket: _dynamic_pad_fn(k, bucket, 32), 32))

    iterator = bucketed_dataset.make_initializable_iterator()
    init_op = iterator.initializer
    get_next = iterator.get_next()

    with self.cached_session() as sess:
      sess.run(init_op)

      # Get two minibatches ([0, 2, ...] and [64, 66, ...])
      which_bucket0, bucketed_values_even0 = sess.run(get_next)
      which_bucket1, bucketed_values_even1 = sess.run(get_next)

      # Ensure that bucket 1 was completely filtered out
      self.assertAllEqual(0, which_bucket0)
      self.assertAllEqual(0, which_bucket1)
      self.assertAllEqual(
          np.arange(0, 64, 2, dtype=np.int64), bucketed_values_even0["x"])
      self.assertAllEqual(
          np.arange(64, 128, 2, dtype=np.int64), bucketed_values_even1["x"])

  def testDynamicWindowSize(self):
    components = np.arange(100).astype(np.int64)

    # Key fn: even/odd
    # Reduce fn: batches of 5
    # Window size fn: even=5, odd=10

    def window_size_func(key):
      window_sizes = constant_op.constant([5, 10], dtype=dtypes.int64)
      return window_sizes[key]

    dataset = dataset_ops.Dataset.from_tensor_slices(components).apply(
        grouping.group_by_window(lambda x: x % 2, lambda _, xs: xs.batch(20),
                                 None, window_size_func))
    iterator = dataset.make_initializable_iterator()
    init_op = iterator.initializer
    get_next = iterator.get_next()

    with self.cached_session() as sess:
      sess.run(init_op)
      with self.assertRaises(errors.OutOfRangeError):
        batches = 0
        while True:
          result = sess.run(get_next)
          is_even = all(x % 2 == 0 for x in result)
          is_odd = all(x % 2 == 1 for x in result)
          self.assertTrue(is_even or is_odd)
          expected_batch_size = 5 if is_even else 10
          self.assertEqual(expected_batch_size, result.shape[0])
          batches += 1

      self.assertEqual(batches, 15)


def _element_length_fn(x, y=None):
  del y
  return array_ops.shape(x)[0]


def _to_sparse_tensor(record):
  return sparse_tensor.SparseTensor(**record)


def _format_record(array, sparse):
  if sparse:
    return {
        "values": array,
        "indices": [[i] for i in range(len(array))],
        "dense_shape": (len(array),)
    }
  return array


def _get_record_type(sparse):
  if sparse:
    return {
        "values": dtypes.int64,
        "indices": dtypes.int64,
        "dense_shape": dtypes.int64
    }
  return dtypes.int32


def _get_record_shape(sparse):
  if sparse:
    return {
        "values": tensor_shape.TensorShape([None,]),
        "indices": tensor_shape.TensorShape([None, 1]),
        "dense_shape": tensor_shape.TensorShape([1,])
    }
  return tensor_shape.TensorShape([None])


class BucketBySequenceLength(test_base.DatasetTestBase):

  def testBucket(self):

    boundaries = [10, 20, 30]
    batch_sizes = [10, 8, 4, 2]
    lengths = [8, 13, 25, 35]

    def build_dataset(sparse):
      def _generator():
        # Produce 1 batch for each bucket
        elements = []
        for batch_size, length in zip(batch_sizes, lengths):
          record_len = length - 1
          for _ in range(batch_size):
            elements.append([1] * record_len)
            record_len = length
        random.shuffle(elements)
        for el in elements:
          yield (_format_record(el, sparse),)
      dataset = dataset_ops.Dataset.from_generator(
          _generator,
          (_get_record_type(sparse),),
          (_get_record_shape(sparse),))
      if sparse:
        dataset = dataset.map(lambda x: (_to_sparse_tensor(x),))
      return dataset

    def _test_bucket_by_padding(no_padding):
      dataset = build_dataset(sparse=no_padding)
      dataset = dataset.apply(
          grouping.bucket_by_sequence_length(
              _element_length_fn,
              boundaries,
              batch_sizes,
              no_padding=no_padding))
      batch, = dataset.make_one_shot_iterator().get_next()

      with self.cached_session() as sess:
        batches = []
        for _ in range(4):
          batches.append(sess.run(batch))
        with self.assertRaises(errors.OutOfRangeError):
          sess.run(batch)
      batch_sizes_val = []
      lengths_val = []
      for batch in batches:
        shape = batch.dense_shape if no_padding else batch.shape
        batch_size = shape[0]
        length = shape[1]
        batch_sizes_val.append(batch_size)
        lengths_val.append(length)
        sum_check = batch.values.sum() if no_padding else batch.sum()
        self.assertEqual(sum_check, batch_size * length - 1)
      self.assertEqual(sum(batch_sizes_val), sum(batch_sizes))
      self.assertEqual(sorted(batch_sizes), sorted(batch_sizes_val))
      self.assertEqual(sorted(lengths), sorted(lengths_val))

    for no_padding in (True, False):
      _test_bucket_by_padding(no_padding)

  def testPadToBoundary(self):

    boundaries = [10, 20, 30]
    batch_sizes = [10, 8, 4, 2]
    lengths = [8, 13, 25]

    def element_gen():
      # Produce 1 batch for each bucket
      elements = []
      for batch_size, length in zip(batch_sizes[:-1], lengths):
        for _ in range(batch_size):
          elements.append([1] * length)
      random.shuffle(elements)
      for el in elements:
        yield (el,)
      for _ in range(batch_sizes[-1]):
        el = [1] * (boundaries[-1] + 5)
        yield (el,)

    element_len = lambda el: array_ops.shape(el)[0]
    dataset = dataset_ops.Dataset.from_generator(
        element_gen, (dtypes.int64,), ([None],)).apply(
            grouping.bucket_by_sequence_length(
                element_len, boundaries, batch_sizes,
                pad_to_bucket_boundary=True))
    batch, = dataset.make_one_shot_iterator().get_next()

    with self.cached_session() as sess:
      batches = []
      for _ in range(3):
        batches.append(sess.run(batch))
      with self.assertRaisesOpError("bucket_boundaries"):
        sess.run(batch)
    batch_sizes_val = []
    lengths_val = []
    for batch in batches:
      batch_size = batch.shape[0]
      length = batch.shape[1]
      batch_sizes_val.append(batch_size)
      lengths_val.append(length)
    batch_sizes = batch_sizes[:-1]
    self.assertEqual(sum(batch_sizes_val), sum(batch_sizes))
    self.assertEqual(sorted(batch_sizes), sorted(batch_sizes_val))
    self.assertEqual([boundary - 1 for boundary in sorted(boundaries)],
                     sorted(lengths_val))

  def testPadToBoundaryNoExtraneousPadding(self):

    boundaries = [3, 7, 11]
    batch_sizes = [2, 2, 2, 2]
    lengths = range(1, 11)

    def element_gen():
      for length in lengths:
        yield ([1] * length,)

    element_len = lambda element: array_ops.shape(element)[0]
    dataset = dataset_ops.Dataset.from_generator(
        element_gen, (dtypes.int64,), ([None],)).apply(
            grouping.bucket_by_sequence_length(
                element_len, boundaries, batch_sizes,
                pad_to_bucket_boundary=True))
    batch, = dataset.make_one_shot_iterator().get_next()

    with self.cached_session() as sess:
      batches = []
      for _ in range(5):
        batches.append(sess.run(batch))
      with self.assertRaises(errors.OutOfRangeError):
        sess.run(batch)

    self.assertAllEqual(batches[0], [[1, 0],
                                     [1, 1]])
    self.assertAllEqual(batches[1], [[1, 1, 1, 0, 0, 0],
                                     [1, 1, 1, 1, 0, 0]])
    self.assertAllEqual(batches[2], [[1, 1, 1, 1, 1, 0],
                                     [1, 1, 1, 1, 1, 1]])
    self.assertAllEqual(batches[3], [[1, 1, 1, 1, 1, 1, 1, 0, 0, 0],
                                     [1, 1, 1, 1, 1, 1, 1, 1, 0, 0]])
    self.assertAllEqual(batches[4], [[1, 1, 1, 1, 1, 1, 1, 1, 1, 0],
                                     [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]])

  def testTupleElements(self):

    def build_dataset(sparse):
      def _generator():
        text = [[1, 2, 3], [3, 4, 5, 6, 7], [1, 2], [8, 9, 0, 2, 3]]
        label = [1, 2, 1, 2]
        for x, y in zip(text, label):
          yield (_format_record(x, sparse), y)
      dataset = dataset_ops.Dataset.from_generator(
          generator=_generator,
          output_types=(_get_record_type(sparse), dtypes.int32),
          output_shapes=(_get_record_shape(sparse),
                         tensor_shape.TensorShape([])))
      if sparse:
        dataset = dataset.map(lambda x, y: (_to_sparse_tensor(x), y))
      return dataset

    def _test_tuple_elements_by_padding(no_padding):
      dataset = build_dataset(sparse=no_padding)
      dataset = dataset.apply(grouping.bucket_by_sequence_length(
          element_length_func=_element_length_fn,
          bucket_batch_sizes=[2, 2, 2],
          bucket_boundaries=[0, 8],
          no_padding=no_padding))
      shapes = dataset.output_shapes
      self.assertEqual([None, None], shapes[0].as_list())
      self.assertEqual([None], shapes[1].as_list())

    for no_padding in (True, False):
      _test_tuple_elements_by_padding(no_padding)

  def testBucketSparse(self):
    """Tests bucketing of sparse tensors (case where `no_padding` == True).

    Test runs on following dataset:
      [
        [0],
        [0, 1],
        [0, 1, 2]
        ...
        [0, ..., max_len - 1]
      ]
    Sequences are bucketed by length and batched with
      `batch_size` < `bucket_size`.
    """

    min_len = 0
    max_len = 100
    batch_size = 7
    bucket_size = 10

    def _build_dataset():
      input_data = [range(i+1) for i in range(min_len, max_len)]
      def generator_fn():
        for record in input_data:
          yield _format_record(record, sparse=True)
      dataset = dataset_ops.Dataset.from_generator(
          generator=generator_fn,
          output_types=_get_record_type(sparse=True))
      dataset = dataset.map(_to_sparse_tensor)
      return dataset

    def _compute_expected_batches():
      """Computes expected batch outputs and stores in a set."""
      all_expected_sparse_tensors = set()
      for bucket_start_len in range(min_len, max_len, bucket_size):
        for batch_offset in range(0, bucket_size, batch_size):
          batch_start_len = bucket_start_len + batch_offset
          batch_end_len = min(batch_start_len + batch_size,
                              bucket_start_len + bucket_size)
          expected_indices = []
          expected_values = []
          for length in range(batch_start_len, batch_end_len):
            for val in range(length + 1):
              expected_indices.append((length - batch_start_len, val))
              expected_values.append(val)
          expected_sprs_tensor = (tuple(expected_indices),
                                  tuple(expected_values))
          all_expected_sparse_tensors.add(expected_sprs_tensor)
      return all_expected_sparse_tensors

    def _compute_batches(dataset):
      """Computes actual batch outputs of dataset and stores in a set."""
      batch = dataset.make_one_shot_iterator().get_next()
      all_sparse_tensors = set()
      with self.cached_session() as sess:
        with self.assertRaises(errors.OutOfRangeError):
          while True:
            output = sess.run(batch)
            sprs_tensor = (tuple([tuple(idx) for idx in output.indices]),
                           tuple(output.values))
            all_sparse_tensors.add(sprs_tensor)
      return all_sparse_tensors

    dataset = _build_dataset()
    boundaries = range(min_len + bucket_size + 1, max_len, bucket_size)
    dataset = dataset.apply(grouping.bucket_by_sequence_length(
        _element_length_fn,
        boundaries,
        [batch_size] * (len(boundaries) + 1),
        no_padding=True))
    batches = _compute_batches(dataset)
    expected_batches = _compute_expected_batches()
    self.assertEqual(batches, expected_batches)


if __name__ == "__main__":
  test.main()

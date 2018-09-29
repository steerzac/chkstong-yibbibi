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
"""Tests for utilities working with arbitrarily nested structures."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from absl.testing import parameterized
import numpy as np

from tensorflow.python.data.util import nest
from tensorflow.python.data.util import structure
from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import ops
from tensorflow.python.framework import sparse_tensor
from tensorflow.python.framework import tensor_shape
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import variables
from tensorflow.python.platform import test


class StructureTest(test.TestCase, parameterized.TestCase):
  # pylint disable=protected-access

  @parameterized.parameters(
      (constant_op.constant(37.0), structure.TensorStructure, [dtypes.float32],
       [[]]), (sparse_tensor.SparseTensor(
           indices=[[3, 4]], values=[-1], dense_shape=[4, 5]),
               structure.SparseTensorStructure, [dtypes.variant], [[3]]),
      ((constant_op.constant(37.0), constant_op.constant([1, 2, 3])),
       structure.NestedStructure, [dtypes.float32, dtypes.int32], [[], [3]]), ({
           "a": constant_op.constant(37.0),
           "b": constant_op.constant([1, 2, 3])
       }, structure.NestedStructure, [dtypes.float32, dtypes.int32], [[], [3]]),
      ({
          "a":
              constant_op.constant(37.0),
          "b": (sparse_tensor.SparseTensor(
              indices=[[0, 0]], values=[1], dense_shape=[1, 1]),
                sparse_tensor.SparseTensor(
                    indices=[[3, 4]], values=[-1], dense_shape=[4, 5]))
      }, structure.NestedStructure,
       [dtypes.float32, dtypes.variant, dtypes.variant], [[], [3], [3]]))
  def testFlatStructure(self, value, expected_structure, expected_types,
                        expected_shapes):
    s = structure.Structure.from_value(value)
    self.assertIsInstance(s, expected_structure)
    self.assertEqual(expected_types, s._flat_types)
    self.assertEqual(expected_shapes, s._flat_shapes)

  @parameterized.parameters(
      (constant_op.constant(37.0), [
          constant_op.constant(38.0),
          array_ops.placeholder(dtypes.float32),
          variables.Variable(100.0), 42.0,
          np.array(42.0, dtype=np.float32)
      ], [constant_op.constant([1.0, 2.0]),
          constant_op.constant(37)]),
      (sparse_tensor.SparseTensor(
          indices=[[3, 4]], values=[-1], dense_shape=[4, 5]),
       [
           sparse_tensor.SparseTensor(
               indices=[[1, 1], [3, 4]], values=[10, -1], dense_shape=[4, 5]),
           sparse_tensor.SparseTensorValue(
               indices=[[1, 1], [3, 4]], values=[10, -1], dense_shape=[4, 5]),
           array_ops.sparse_placeholder(dtype=dtypes.int32),
           array_ops.sparse_placeholder(dtype=dtypes.int32, shape=[None, None])
       ], [
           constant_op.constant(37, shape=[4, 5]),
           sparse_tensor.SparseTensor(
               indices=[[3, 4]], values=[-1], dense_shape=[5, 6]),
           array_ops.sparse_placeholder(
               dtype=dtypes.int32, shape=[None, None, None]),
           sparse_tensor.SparseTensor(
               indices=[[3, 4]], values=[-1.0], dense_shape=[4, 5])
       ]),
      ({
          "a": constant_op.constant(37.0),
          "b": constant_op.constant([1, 2, 3])
      }, [{
          "a": constant_op.constant(15.0),
          "b": constant_op.constant([4, 5, 6])
      }], [{
          "a": constant_op.constant(15.0),
          "b": constant_op.constant([4, 5, 6, 7])
      }, {
          "a": constant_op.constant(15),
          "b": constant_op.constant([4, 5, 6])
      }, {
          "a":
              constant_op.constant(15),
          "b":
              sparse_tensor.SparseTensor(
                  indices=[[0], [1], [2]], values=[4, 5, 6], dense_shape=[3])
      }, (constant_op.constant(15.0), constant_op.constant([4, 5, 6]))]),
  )
  def testIsCompatibleWithStructure(self, original_value, compatible_values,
                                    incompatible_values):
    s = structure.Structure.from_value(original_value)
    for compatible_value in compatible_values:
      self.assertTrue(
          s.is_compatible_with(
              structure.Structure.from_value(compatible_value)))
    for incompatible_value in incompatible_values:
      self.assertFalse(
          s.is_compatible_with(
              structure.Structure.from_value(incompatible_value)))

  # NOTE(mrry): The arguments must be lifted into lambdas because otherwise they
  # will be executed before the (eager- or graph-mode) test environment has been
  # set up.
  # pylint: disable=g-long-lambda
  @parameterized.parameters(
      (lambda: constant_op.constant(37.0),),
      (lambda: sparse_tensor.SparseTensor(
          indices=[[3, 4]], values=[-1], dense_shape=[4, 5]),),
      (lambda: {"a": constant_op.constant(37.0),
                "b": constant_op.constant([1, 2, 3])},),
      (lambda: {"a": constant_op.constant(37.0),
                "b": (sparse_tensor.SparseTensor(
                    indices=[[0, 0]], values=[1], dense_shape=[1, 1]),
                      sparse_tensor.SparseTensor(
                          indices=[[3, 4]], values=[-1], dense_shape=[4, 5]))
               },),
      )
  def testRoundTripConversion(self, value_fn):
    value = value_fn()
    s = structure.Structure.from_value(value)
    before = self.evaluate(value)
    after = self.evaluate(s._from_tensor_list(s._to_tensor_list(value)))

    flat_before = nest.flatten(before)
    flat_after = nest.flatten(after)
    for b, a in zip(flat_before, flat_after):
      if isinstance(b, sparse_tensor.SparseTensorValue):
        self.assertAllEqual(b.indices, a.indices)
        self.assertAllEqual(b.values, a.values)
        self.assertAllEqual(b.dense_shape, a.dense_shape)
      else:
        self.assertAllEqual(b, a)
  # pylint: enable=g-long-lambda

  def testIncompatibleStructure(self):
    # Define three mutually incompatible values/structures, and assert that:
    # 1. Using one structure to flatten a value with an incompatible structure
    #    fails.
    # 2. Using one structure to restructre a flattened value with an
    #    incompatible structure fails.
    value_tensor = constant_op.constant(42.0)
    s_tensor = structure.Structure.from_value(value_tensor)
    flat_tensor = s_tensor._to_tensor_list(value_tensor)

    value_sparse_tensor = sparse_tensor.SparseTensor(
        indices=[[0, 0]], values=[1], dense_shape=[1, 1])
    s_sparse_tensor = structure.Structure.from_value(value_sparse_tensor)
    flat_sparse_tensor = s_sparse_tensor._to_tensor_list(value_sparse_tensor)

    value_nest = {
        "a": constant_op.constant(37.0),
        "b": constant_op.constant([1, 2, 3])
    }
    s_nest = structure.Structure.from_value(value_nest)
    flat_nest = s_nest._to_tensor_list(value_nest)

    with self.assertRaisesRegexp(
        ValueError, r"SparseTensor.* is not convertible to a tensor with "
        r"dtype.*float32.* and shape \(\)"):
      s_tensor._to_tensor_list(value_sparse_tensor)
    with self.assertRaisesRegexp(
        ValueError, r"Value \{.*\} is not convertible to a tensor with "
        r"dtype.*float32.* and shape \(\)"):
      s_tensor._to_tensor_list(value_nest)

    with self.assertRaisesRegexp(TypeError, "Input must be a SparseTensor"):
      s_sparse_tensor._to_tensor_list(value_tensor)

    with self.assertRaisesRegexp(TypeError, "Input must be a SparseTensor"):
      s_sparse_tensor._to_tensor_list(value_nest)

    with self.assertRaisesRegexp(
        ValueError, "Tensor.* not compatible with the nested structure "
        ".*TensorStructure.*TensorStructure"):
      s_nest._to_tensor_list(value_tensor)

    with self.assertRaisesRegexp(
        ValueError, "SparseTensor.* not compatible with the nested structure "
        ".*TensorStructure.*TensorStructure"):
      s_nest._to_tensor_list(value_sparse_tensor)

    with self.assertRaisesRegexp(
        ValueError, r"Cannot convert.*with dtype.*float32.* and shape \(\)"):
      s_tensor._from_tensor_list(flat_sparse_tensor)

    with self.assertRaisesRegexp(
        ValueError, "TensorStructure corresponds to a single tf.Tensor."):
      s_tensor._from_tensor_list(flat_nest)

    with self.assertRaisesRegexp(
        ValueError, "SparseTensorStructure corresponds to a single tf.variant "
        "vector of length 3."):
      s_sparse_tensor._from_tensor_list(flat_tensor)

    with self.assertRaisesRegexp(
        ValueError, "SparseTensorStructure corresponds to a single tf.variant "
        "vector of length 3."):
      s_sparse_tensor._from_tensor_list(flat_nest)

    with self.assertRaisesRegexp(
        ValueError, "Expected 2 flat values in NestedStructure but got 1."):
      s_nest._from_tensor_list(flat_tensor)

    with self.assertRaisesRegexp(
        ValueError, "Expected 2 flat values in NestedStructure but got 1."):
      s_nest._from_tensor_list(flat_sparse_tensor)

  def testIncompatibleNestedStructure(self):
    # Define three mutually incompatible nested values/structures, and assert
    # that:
    # 1. Using one structure to flatten a value with an incompatible structure
    #    fails.
    # 2. Using one structure to restructre a flattened value with an
    #    incompatible structure fails.

    value_0 = {
        "a": constant_op.constant(37.0),
        "b": constant_op.constant([1, 2, 3])
    }
    s_0 = structure.Structure.from_value(value_0)
    flat_s_0 = s_0._to_tensor_list(value_0)

    # `value_1` has compatible nested structure with `value_0`, but different
    # classes.
    value_1 = {
        "a":
            constant_op.constant(37.0),
        "b":
            sparse_tensor.SparseTensor(
                indices=[[0, 0]], values=[1], dense_shape=[1, 1])
    }
    s_1 = structure.Structure.from_value(value_1)
    flat_s_1 = s_1._to_tensor_list(value_1)

    # `value_2` has incompatible nested structure with `value_0` and `value_1`.
    value_2 = {
        "a":
            constant_op.constant(37.0),
        "b": (sparse_tensor.SparseTensor(
            indices=[[0, 0]], values=[1], dense_shape=[1, 1]),
              sparse_tensor.SparseTensor(
                  indices=[[3, 4]], values=[-1], dense_shape=[4, 5]))
    }
    s_2 = structure.Structure.from_value(value_2)
    flat_s_2 = s_2._to_tensor_list(value_2)

    with self.assertRaisesRegexp(
        ValueError, "SparseTensor.* not compatible with the nested structure "
        ".*TensorStructure"):
      s_0._to_tensor_list(value_1)

    with self.assertRaisesRegexp(
        ValueError, "SparseTensor.*SparseTensor.* not compatible with the "
        "nested structure .*TensorStructure"):
      s_0._to_tensor_list(value_2)

    with self.assertRaisesRegexp(
        ValueError, "Tensor.* not compatible with the nested structure "
        ".*SparseTensorStructure"):
      s_1._to_tensor_list(value_0)

    with self.assertRaisesRegexp(
        ValueError, "SparseTensor.*SparseTensor.* not compatible with the "
        "nested structure .*TensorStructure"):
      s_0._to_tensor_list(value_2)

    # NOTE(mrry): The repr of the dictionaries is not sorted, so the regexp
    # needs to account for "a" coming before or after "b". It might be worth
    # adding a deterministic repr for these error messages (among other
    # improvements).
    with self.assertRaisesRegexp(
        ValueError, "Tensor.*Tensor.* not compatible with the nested structure "
        ".*(TensorStructure.*SparseTensorStructure.*SparseTensorStructure|"
        "SparseTensorStructure.*SparseTensorStructure.*TensorStructure)"):
      s_2._to_tensor_list(value_0)

    with self.assertRaisesRegexp(
        ValueError, "(Tensor.*SparseTensor|SparseTensor.*Tensor).* "
        "not compatible with the nested structure .*"
        "(TensorStructure.*SparseTensorStructure.*SparseTensorStructure|"
        "SparseTensorStructure.*SparseTensorStructure.*TensorStructure)"):
      s_2._to_tensor_list(value_1)

    with self.assertRaisesRegexp(
        ValueError, r"Cannot convert.*with dtype.*int32.* and shape \(3,\)"):
      s_0._from_tensor_list(flat_s_1)

    with self.assertRaisesRegexp(
        ValueError, "Expected 2 flat values in NestedStructure but got 3."):
      s_0._from_tensor_list(flat_s_2)

    with self.assertRaisesRegexp(
        ValueError, "SparseTensorStructure corresponds to a single tf.variant "
        "vector of length 3."):
      s_1._from_tensor_list(flat_s_0)

    with self.assertRaisesRegexp(
        ValueError, "Expected 2 flat values in NestedStructure but got 3."):
      s_1._from_tensor_list(flat_s_2)

    with self.assertRaisesRegexp(
        ValueError, "Expected 3 flat values in NestedStructure but got 2."):
      s_2._from_tensor_list(flat_s_0)

    with self.assertRaisesRegexp(
        ValueError, "Expected 3 flat values in NestedStructure but got 2."):
      s_2._from_tensor_list(flat_s_1)

  @parameterized.named_parameters(
      ("Tensor", dtypes.float32, tensor_shape.scalar(), ops.Tensor,
       structure.TensorStructure(dtypes.float32, [])),
      ("SparseTensor", dtypes.int32, tensor_shape.matrix(2, 2),
       sparse_tensor.SparseTensor,
       structure.SparseTensorStructure(dtypes.int32, [2, 2])),
      ("Nest",
       {"a": dtypes.float32, "b": (dtypes.int32, dtypes.string)},
       {"a": tensor_shape.scalar(),
        "b": (tensor_shape.matrix(2, 2), tensor_shape.scalar())},
       {"a": ops.Tensor, "b": (sparse_tensor.SparseTensor, ops.Tensor)},
       structure.NestedStructure({
           "a": structure.TensorStructure(dtypes.float32, []),
           "b": (structure.SparseTensorStructure(dtypes.int32, [2, 2]),
                 structure.TensorStructure(dtypes.string, []))})),
  )
  def testFromLegacyStructure(self, output_types, output_shapes, output_classes,
                              expected_structure):
    actual_structure = structure.Structure._from_legacy_structure(
        output_types, output_shapes, output_classes)
    self.assertTrue(expected_structure.is_compatible_with(actual_structure))
    self.assertTrue(actual_structure.is_compatible_with(expected_structure))

if __name__ == "__main__":
  test.main()

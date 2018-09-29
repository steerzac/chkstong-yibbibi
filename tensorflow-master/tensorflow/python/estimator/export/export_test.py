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
"""Tests for export."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import tempfile
import time

from google.protobuf import text_format

from tensorflow.core.example import example_pb2
from tensorflow.python.estimator.export import export
from tensorflow.python.estimator.export import export_output
from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import ops
from tensorflow.python.framework import sparse_tensor
from tensorflow.python.framework import tensor_shape
from tensorflow.python.framework import test_util
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import parsing_ops
from tensorflow.python.platform import test
from tensorflow.python.saved_model import signature_constants
from tensorflow.python.saved_model import signature_def_utils


class LabeledTensorMock(object):
  """Mock class emulating LabeledTensor."""

  def __init__(self):
    self.tensor = constant_op.constant([1])


def _convert_labeled_tensor_mock_to_tensor(value, *args, **kwargs):
  return ops.internal_convert_to_tensor(value.tensor, *args, **kwargs)


ops.register_tensor_conversion_function(LabeledTensorMock,
                                        _convert_labeled_tensor_mock_to_tensor)


class ServingInputReceiverTest(test_util.TensorFlowTestCase):

  def test_serving_input_receiver_constructor(self):
    """Tests that no errors are raised when input is expected."""
    features = {
        "feature0": constant_op.constant([0]),
        u"feature1": constant_op.constant([1]),
        "feature2": sparse_tensor.SparseTensor(
            indices=[[0, 0]], values=[1], dense_shape=[1, 1]),
    }
    receiver_tensors = {
        "example0": array_ops.placeholder(dtypes.string, name="example0"),
        u"example1": array_ops.placeholder(dtypes.string, name="example1"),
    }
    export.ServingInputReceiver(features, receiver_tensors)

  def test_serving_input_receiver_features_invalid(self):
    receiver_tensors = {
        "example0": array_ops.placeholder(dtypes.string, name="example0"),
        u"example1": array_ops.placeholder(dtypes.string, name="example1"),
    }

    with self.assertRaisesRegexp(ValueError, "features must be defined"):
      export.ServingInputReceiver(
          features=None,
          receiver_tensors=receiver_tensors)

    with self.assertRaisesRegexp(ValueError, "feature keys must be strings"):
      export.ServingInputReceiver(
          features={1: constant_op.constant([1])},
          receiver_tensors=receiver_tensors)

    with self.assertRaisesRegexp(
        ValueError, "feature feature1 must be a Tensor or SparseTensor"):
      export.ServingInputReceiver(
          features={"feature1": [1]},
          receiver_tensors=receiver_tensors)

  def test_serving_input_receiver_receiver_tensors_invalid(self):
    features = {
        "feature0": constant_op.constant([0]),
        u"feature1": constant_op.constant([1]),
        "feature2": sparse_tensor.SparseTensor(
            indices=[[0, 0]], values=[1], dense_shape=[1, 1]),
    }

    with self.assertRaisesRegexp(
        ValueError, "receiver_tensors must be defined"):
      export.ServingInputReceiver(
          features=features,
          receiver_tensors=None)

    with self.assertRaisesRegexp(
        ValueError, "receiver_tensor keys must be strings"):
      export.ServingInputReceiver(
          features=features,
          receiver_tensors={
              1: array_ops.placeholder(dtypes.string, name="example0")})

    with self.assertRaisesRegexp(
        ValueError, "receiver_tensor example1 must be a Tensor"):
      export.ServingInputReceiver(
          features=features,
          receiver_tensors={"example1": [1]})

  def test_single_feature_single_receiver(self):
    feature = constant_op.constant(5)
    receiver_tensor = array_ops.placeholder(dtypes.string)
    input_receiver = export.ServingInputReceiver(
        feature, receiver_tensor)
    # single feature is automatically named
    feature_key, = input_receiver.features.keys()
    self.assertEqual("feature", feature_key)
    # single receiver is automatically named
    receiver_key, = input_receiver.receiver_tensors.keys()
    self.assertEqual("input", receiver_key)

  def test_multi_feature_single_receiver(self):
    features = {"foo": constant_op.constant(5),
                "bar": constant_op.constant(6)}
    receiver_tensor = array_ops.placeholder(dtypes.string)
    _ = export.ServingInputReceiver(features, receiver_tensor)

  def test_multi_feature_multi_receiver(self):
    features = {"foo": constant_op.constant(5),
                "bar": constant_op.constant(6)}
    receiver_tensors = {"baz": array_ops.placeholder(dtypes.int64),
                        "qux": array_ops.placeholder(dtypes.float32)}
    _ = export.ServingInputReceiver(features, receiver_tensors)

  def test_feature_wrong_type(self):
    feature = "not a tensor"
    receiver_tensor = array_ops.placeholder(dtypes.string)
    with self.assertRaises(ValueError):
      _ = export.ServingInputReceiver(feature, receiver_tensor)

  def test_feature_labeled_tensor(self):
    feature = LabeledTensorMock()
    receiver_tensor = array_ops.placeholder(dtypes.string)
    _ = export.ServingInputReceiver(feature, receiver_tensor)

  def test_receiver_wrong_type(self):
    feature = constant_op.constant(5)
    receiver_tensor = "not a tensor"
    with self.assertRaises(ValueError):
      _ = export.ServingInputReceiver(feature, receiver_tensor)


class UnsupervisedInputReceiverTest(test_util.TensorFlowTestCase):

  # Since this is basically a wrapper around ServingInputReceiver, we only
  # have a simple sanity check to ensure that it works.

  def test_unsupervised_input_receiver_constructor(self):
    """Tests that no errors are raised when input is expected."""
    features = {
        "feature0":
            constant_op.constant([0]),
        u"feature1":
            constant_op.constant([1]),
        "feature2":
            sparse_tensor.SparseTensor(
                indices=[[0, 0]], values=[1], dense_shape=[1, 1]),
    }
    receiver_tensors = {
        "example0": array_ops.placeholder(dtypes.string, name="example0"),
        u"example1": array_ops.placeholder(dtypes.string, name="example1"),
    }
    export.UnsupervisedInputReceiver(features, receiver_tensors)


class SupervisedInputReceiverTest(test_util.TensorFlowTestCase):

  def test_input_receiver_constructor(self):
    """Tests that no errors are raised when input is expected."""
    features = {
        "feature0": constant_op.constant([0]),
        u"feature1": constant_op.constant([1]),
        "feature2": sparse_tensor.SparseTensor(
            indices=[[0, 0]], values=[1], dense_shape=[1, 1]),
    }
    labels = {
        "classes": constant_op.constant([0] * 100),
    }

    receiver_tensors = {
        "example0": array_ops.placeholder(dtypes.string, name="example0"),
        u"example1": array_ops.placeholder(dtypes.string, name="example1"),
    }
    export.SupervisedInputReceiver(features, labels, receiver_tensors)

  def test_input_receiver_raw_values(self):
    """Tests that no errors are raised when input is expected."""
    features = {
        "feature0": constant_op.constant([0]),
        u"feature1": constant_op.constant([1]),
        "feature2": sparse_tensor.SparseTensor(
            indices=[[0, 0]], values=[1], dense_shape=[1, 1]),
    }

    labels = {
        "classes": constant_op.constant([0] * 100),
    }

    receiver_tensors = {
        "example0": array_ops.placeholder(dtypes.string, name="example0"),
        u"example1": array_ops.placeholder(dtypes.string, name="example1"),
    }
    rec = export.SupervisedInputReceiver(
        features["feature2"], labels, receiver_tensors)
    self.assertIsInstance(rec.features, sparse_tensor.SparseTensor)

    rec = export.SupervisedInputReceiver(
        features, labels["classes"], receiver_tensors)
    self.assertIsInstance(rec.labels, ops.Tensor)

  def test_input_receiver_features_invalid(self):
    features = constant_op.constant([0] * 100)
    labels = constant_op.constant([0])
    receiver_tensors = {
        "example0": array_ops.placeholder(dtypes.string, name="example0"),
        u"example1": array_ops.placeholder(dtypes.string, name="example1"),
    }

    with self.assertRaisesRegexp(ValueError, "features must be defined"):
      export.SupervisedInputReceiver(
          features=None,
          labels=labels,
          receiver_tensors=receiver_tensors)

    with self.assertRaisesRegexp(ValueError, "feature keys must be strings"):
      export.SupervisedInputReceiver(
          features={1: constant_op.constant([1])},
          labels=labels,
          receiver_tensors=receiver_tensors)

    with self.assertRaisesRegexp(ValueError, "label keys must be strings"):
      export.SupervisedInputReceiver(
          features=features,
          labels={1: constant_op.constant([1])},
          receiver_tensors=receiver_tensors)

    with self.assertRaisesRegexp(
        ValueError, "feature feature1 must be a Tensor or SparseTensor"):
      export.SupervisedInputReceiver(
          features={"feature1": [1]},
          labels=labels,
          receiver_tensors=receiver_tensors)

    with self.assertRaisesRegexp(
        ValueError, "feature must be a Tensor or SparseTensor"):
      export.SupervisedInputReceiver(
          features=[1],
          labels=labels,
          receiver_tensors=receiver_tensors)

    with self.assertRaisesRegexp(
        ValueError, "label must be a Tensor or SparseTensor"):
      export.SupervisedInputReceiver(
          features=features,
          labels=100,
          receiver_tensors=receiver_tensors)

  def test_input_receiver_receiver_tensors_invalid(self):
    features = {
        "feature0": constant_op.constant([0]),
        u"feature1": constant_op.constant([1]),
        "feature2": sparse_tensor.SparseTensor(
            indices=[[0, 0]], values=[1], dense_shape=[1, 1]),
    }
    labels = constant_op.constant([0])

    with self.assertRaisesRegexp(
        ValueError, "receiver_tensors must be defined"):
      export.SupervisedInputReceiver(
          features=features,
          labels=labels,
          receiver_tensors=None)

    with self.assertRaisesRegexp(
        ValueError, "receiver_tensor keys must be strings"):
      export.SupervisedInputReceiver(
          features=features,
          labels=labels,
          receiver_tensors={
              1: array_ops.placeholder(dtypes.string, name="example0")})

    with self.assertRaisesRegexp(
        ValueError, "receiver_tensor example1 must be a Tensor"):
      export.SupervisedInputReceiver(
          features=features,
          labels=labels,
          receiver_tensors={"example1": [1]})

  def test_single_feature_single_receiver(self):
    feature = constant_op.constant(5)
    label = constant_op.constant(5)
    receiver_tensor = array_ops.placeholder(dtypes.string)
    input_receiver = export.SupervisedInputReceiver(
        feature, label, receiver_tensor)

    # single receiver is automatically named
    receiver_key, = input_receiver.receiver_tensors.keys()
    self.assertEqual("input", receiver_key)

  def test_multi_feature_single_receiver(self):
    features = {"foo": constant_op.constant(5),
                "bar": constant_op.constant(6)}
    labels = {"value": constant_op.constant(5)}
    receiver_tensor = array_ops.placeholder(dtypes.string)
    _ = export.SupervisedInputReceiver(features, labels, receiver_tensor)

  def test_multi_feature_multi_receiver(self):
    features = {"foo": constant_op.constant(5),
                "bar": constant_op.constant(6)}
    labels = {"value": constant_op.constant(5)}
    receiver_tensors = {"baz": array_ops.placeholder(dtypes.int64),
                        "qux": array_ops.placeholder(dtypes.float32)}
    _ = export.SupervisedInputReceiver(features, labels, receiver_tensors)

  def test_feature_labeled_tensor(self):
    feature = LabeledTensorMock()
    label = constant_op.constant(5)
    receiver_tensor = array_ops.placeholder(dtypes.string)
    _ = export.SupervisedInputReceiver(feature, label, receiver_tensor)


class ExportTest(test_util.TensorFlowTestCase):

  def test_build_parsing_serving_input_receiver_fn(self):
    feature_spec = {"int_feature": parsing_ops.VarLenFeature(dtypes.int64),
                    "float_feature": parsing_ops.VarLenFeature(dtypes.float32)}
    serving_input_receiver_fn = export.build_parsing_serving_input_receiver_fn(
        feature_spec)
    with ops.Graph().as_default():
      serving_input_receiver = serving_input_receiver_fn()
      self.assertEqual(set(["int_feature", "float_feature"]),
                       set(serving_input_receiver.features.keys()))
      self.assertEqual(set(["examples"]),
                       set(serving_input_receiver.receiver_tensors.keys()))

      example = example_pb2.Example()
      text_format.Parse("features: { "
                        "  feature: { "
                        "    key: 'int_feature' "
                        "    value: { "
                        "      int64_list: { "
                        "        value: [ 21, 2, 5 ] "
                        "      } "
                        "    } "
                        "  } "
                        "  feature: { "
                        "    key: 'float_feature' "
                        "    value: { "
                        "      float_list: { "
                        "        value: [ 525.25 ] "
                        "      } "
                        "    } "
                        "  } "
                        "} ", example)

      with self.cached_session() as sess:
        sparse_result = sess.run(
            serving_input_receiver.features,
            feed_dict={
                serving_input_receiver.receiver_tensors["examples"].name:
                [example.SerializeToString()]})
        self.assertAllEqual([[0, 0], [0, 1], [0, 2]],
                            sparse_result["int_feature"].indices)
        self.assertAllEqual([21, 2, 5],
                            sparse_result["int_feature"].values)
        self.assertAllEqual([[0, 0]],
                            sparse_result["float_feature"].indices)
        self.assertAllEqual([525.25],
                            sparse_result["float_feature"].values)

  def test_build_raw_serving_input_receiver_fn_name(self):
    """Test case for issue #12755."""
    f = {
        "feature":
            array_ops.placeholder(
                name="feature", shape=[32], dtype=dtypes.float32)
    }
    serving_input_receiver_fn = export.build_raw_serving_input_receiver_fn(f)
    v = serving_input_receiver_fn()
    self.assertTrue(isinstance(v, export.ServingInputReceiver))

  def test_build_raw_serving_input_receiver_fn_without_shape(self):
    """Test case for issue #21178."""
    f = {"feature_1": array_ops.placeholder(dtypes.float32),
         "feature_2": array_ops.placeholder(dtypes.int32)}
    serving_input_receiver_fn = export.build_raw_serving_input_receiver_fn(f)
    v = serving_input_receiver_fn()
    self.assertTrue(isinstance(v, export.ServingInputReceiver))
    self.assertEqual(
        tensor_shape.unknown_shape(),
        v.receiver_tensors["feature_1"].shape)
    self.assertEqual(
        tensor_shape.unknown_shape(),
        v.receiver_tensors["feature_2"].shape)

  @test_util.run_in_graph_and_eager_modes
  def test_build_raw_serving_input_receiver_fn(self):
    features = {"feature_1": constant_op.constant(["hello"]),
                "feature_2": constant_op.constant([42])}
    serving_input_receiver_fn = export.build_raw_serving_input_receiver_fn(
        features)
    with ops.Graph().as_default():
      serving_input_receiver = serving_input_receiver_fn()
      self.assertEqual(set(["feature_1", "feature_2"]),
                       set(serving_input_receiver.features.keys()))
      self.assertEqual(set(["feature_1", "feature_2"]),
                       set(serving_input_receiver.receiver_tensors.keys()))
      self.assertEqual(
          dtypes.string,
          serving_input_receiver.receiver_tensors["feature_1"].dtype)
      self.assertEqual(
          dtypes.int32,
          serving_input_receiver.receiver_tensors["feature_2"].dtype)

  @test_util.run_in_graph_and_eager_modes
  def test_build_raw_supervised_input_receiver_fn(self):
    features = {"feature_1": constant_op.constant(["hello"]),
                "feature_2": constant_op.constant([42])}
    labels = {"foo": constant_op.constant([5]),
              "bar": constant_op.constant([6])}
    input_receiver_fn = export.build_raw_supervised_input_receiver_fn(
        features, labels)
    with ops.Graph().as_default():
      input_receiver = input_receiver_fn()
      self.assertEqual(set(["feature_1", "feature_2"]),
                       set(input_receiver.features.keys()))
      self.assertEqual(set(["foo", "bar"]),
                       set(input_receiver.labels.keys()))
      self.assertEqual(set(["feature_1", "feature_2", "foo", "bar"]),
                       set(input_receiver.receiver_tensors.keys()))
      self.assertEqual(
          dtypes.string, input_receiver.receiver_tensors["feature_1"].dtype)
      self.assertEqual(
          dtypes.int32, input_receiver.receiver_tensors["feature_2"].dtype)

  @test_util.run_in_graph_and_eager_modes
  def test_build_raw_supervised_input_receiver_fn_raw_tensors(self):
    features = {"feature_1": constant_op.constant(["hello"]),
                "feature_2": constant_op.constant([42])}
    labels = {"foo": constant_op.constant([5]),
              "bar": constant_op.constant([6])}
    input_receiver_fn1 = export.build_raw_supervised_input_receiver_fn(
        features["feature_1"], labels)
    input_receiver_fn2 = export.build_raw_supervised_input_receiver_fn(
        features["feature_1"], labels["foo"])
    with ops.Graph().as_default():
      input_receiver = input_receiver_fn1()
      self.assertIsInstance(input_receiver.features, ops.Tensor)
      self.assertEqual(set(["foo", "bar"]),
                       set(input_receiver.labels.keys()))
      self.assertEqual(set(["input", "foo", "bar"]),
                       set(input_receiver.receiver_tensors.keys()))

      input_receiver = input_receiver_fn2()
      self.assertIsInstance(input_receiver.features, ops.Tensor)
      self.assertIsInstance(input_receiver.labels, ops.Tensor)
      self.assertEqual(set(["input", "label"]),
                       set(input_receiver.receiver_tensors.keys()))

  @test_util.run_in_graph_and_eager_modes
  def test_build_raw_supervised_input_receiver_fn_batch_size(self):
    features = {"feature_1": constant_op.constant(["hello"]),
                "feature_2": constant_op.constant([42])}
    labels = {"foo": constant_op.constant([5]),
              "bar": constant_op.constant([6])}
    input_receiver_fn = export.build_raw_supervised_input_receiver_fn(
        features, labels, default_batch_size=10)
    with ops.Graph().as_default():
      input_receiver = input_receiver_fn()
      self.assertEqual([10], input_receiver.receiver_tensors["feature_1"].shape)
      self.assertEqual([10], input_receiver.features["feature_1"].shape)

  @test_util.run_in_graph_and_eager_modes
  def test_build_raw_supervised_input_receiver_fn_overlapping_keys(self):
    features = {"feature_1": constant_op.constant(["hello"]),
                "feature_2": constant_op.constant([42])}
    labels = {"feature_1": constant_op.constant([5]),
              "bar": constant_op.constant([6])}
    with self.assertRaises(ValueError):
      export.build_raw_supervised_input_receiver_fn(features, labels)

  @test_util.run_in_graph_and_eager_modes
  def test_build_supervised_input_receiver_fn_from_input_fn(self):
    def dummy_input_fn():
      return ({"x": constant_op.constant([[1], [1]]),
               "y": constant_op.constant(["hello", "goodbye"])},
              constant_op.constant([[1], [1]]))

    input_receiver_fn = export.build_supervised_input_receiver_fn_from_input_fn(
        dummy_input_fn)

    with ops.Graph().as_default():
      input_receiver = input_receiver_fn()
      self.assertEqual(set(["x", "y"]),
                       set(input_receiver.features.keys()))
      self.assertIsInstance(input_receiver.labels, ops.Tensor)
      self.assertEqual(set(["x", "y", "label"]),
                       set(input_receiver.receiver_tensors.keys()))

  @test_util.run_in_graph_and_eager_modes
  def test_build_supervised_input_receiver_fn_from_input_fn_args(self):
    def dummy_input_fn(feature_key="x"):
      return ({feature_key: constant_op.constant([[1], [1]]),
               "y": constant_op.constant(["hello", "goodbye"])},
              {"my_label": constant_op.constant([[1], [1]])})

    input_receiver_fn = export.build_supervised_input_receiver_fn_from_input_fn(
        dummy_input_fn, feature_key="z")

    with ops.Graph().as_default():
      input_receiver = input_receiver_fn()
      self.assertEqual(set(["z", "y"]),
                       set(input_receiver.features.keys()))
      self.assertEqual(set(["my_label"]),
                       set(input_receiver.labels.keys()))
      self.assertEqual(set(["z", "y", "my_label"]),
                       set(input_receiver.receiver_tensors.keys()))

  def test_build_all_signature_defs_without_receiver_alternatives(self):
    receiver_tensor = array_ops.placeholder(dtypes.string)
    output_1 = constant_op.constant([1.])
    output_2 = constant_op.constant(["2"])
    output_3 = constant_op.constant(["3"])
    export_outputs = {
        signature_constants.DEFAULT_SERVING_SIGNATURE_DEF_KEY:
            export_output.RegressionOutput(value=output_1),
        "head-2": export_output.ClassificationOutput(classes=output_2),
        "head-3": export_output.PredictOutput(outputs={
            "some_output_3": output_3
        }),
    }

    signature_defs = export.build_all_signature_defs(
        receiver_tensor, export_outputs)

    expected_signature_defs = {
        "serving_default":
            signature_def_utils.regression_signature_def(receiver_tensor,
                                                         output_1),
        "head-2":
            signature_def_utils.classification_signature_def(receiver_tensor,
                                                             output_2, None),
        "head-3":
            signature_def_utils.predict_signature_def({
                "input": receiver_tensor
            }, {"some_output_3": output_3})
    }

    self.assertDictEqual(expected_signature_defs, signature_defs)

  def test_build_all_signature_defs_with_dict_alternatives(self):
    receiver_tensor = array_ops.placeholder(dtypes.string)
    receiver_tensors_alternative_1 = {
        "foo": array_ops.placeholder(dtypes.int64),
        "bar": array_ops.sparse_placeholder(dtypes.float32)}
    receiver_tensors_alternatives = {"other": receiver_tensors_alternative_1}
    output_1 = constant_op.constant([1.])
    output_2 = constant_op.constant(["2"])
    output_3 = constant_op.constant(["3"])
    export_outputs = {
        signature_constants.DEFAULT_SERVING_SIGNATURE_DEF_KEY:
            export_output.RegressionOutput(value=output_1),
        "head-2": export_output.ClassificationOutput(classes=output_2),
        "head-3": export_output.PredictOutput(outputs={
            "some_output_3": output_3
        }),
    }

    signature_defs = export.build_all_signature_defs(
        receiver_tensor, export_outputs, receiver_tensors_alternatives)

    expected_signature_defs = {
        "serving_default":
            signature_def_utils.regression_signature_def(
                receiver_tensor,
                output_1),
        "head-2":
            signature_def_utils.classification_signature_def(
                receiver_tensor,
                output_2, None),
        "head-3":
            signature_def_utils.predict_signature_def(
                {"input": receiver_tensor},
                {"some_output_3": output_3}),
        "other:head-3":
            signature_def_utils.predict_signature_def(
                receiver_tensors_alternative_1,
                {"some_output_3": output_3})

        # Note that the alternatives 'other:serving_default' and 'other:head-2'
        # are invalid, because regession and classification signatures must take
        # a single string input.  Here we verify that these invalid signatures
        # are not included in the export.
    }

    self.assertDictEqual(expected_signature_defs, signature_defs)

  def test_build_all_signature_defs_with_single_alternatives(self):
    receiver_tensor = array_ops.placeholder(dtypes.string)
    receiver_tensors_alternative_1 = array_ops.placeholder(dtypes.int64)
    receiver_tensors_alternative_2 = array_ops.sparse_placeholder(
        dtypes.float32)
    # Note we are passing single Tensors as values of
    # receiver_tensors_alternatives, where normally that is a dict.
    # In this case a dict will be created using the default receiver tensor
    # name "input".
    receiver_tensors_alternatives = {"other1": receiver_tensors_alternative_1,
                                     "other2": receiver_tensors_alternative_2}
    output_1 = constant_op.constant([1.])
    output_2 = constant_op.constant(["2"])
    output_3 = constant_op.constant(["3"])
    export_outputs = {
        signature_constants.DEFAULT_SERVING_SIGNATURE_DEF_KEY:
            export_output.RegressionOutput(value=output_1),
        "head-2": export_output.ClassificationOutput(classes=output_2),
        "head-3": export_output.PredictOutput(outputs={
            "some_output_3": output_3
        }),
    }

    signature_defs = export.build_all_signature_defs(
        receiver_tensor, export_outputs, receiver_tensors_alternatives)

    expected_signature_defs = {
        "serving_default":
            signature_def_utils.regression_signature_def(
                receiver_tensor,
                output_1),
        "head-2":
            signature_def_utils.classification_signature_def(
                receiver_tensor,
                output_2, None),
        "head-3":
            signature_def_utils.predict_signature_def(
                {"input": receiver_tensor},
                {"some_output_3": output_3}),
        "other1:head-3":
            signature_def_utils.predict_signature_def(
                {"input": receiver_tensors_alternative_1},
                {"some_output_3": output_3}),
        "other2:head-3":
            signature_def_utils.predict_signature_def(
                {"input": receiver_tensors_alternative_2},
                {"some_output_3": output_3})

        # Note that the alternatives 'other:serving_default' and 'other:head-2'
        # are invalid, because regession and classification signatures must take
        # a single string input.  Here we verify that these invalid signatures
        # are not included in the export.
    }

    self.assertDictEqual(expected_signature_defs, signature_defs)

  def test_build_all_signature_defs_export_outputs_required(self):
    receiver_tensor = constant_op.constant(["11"])

    with self.assertRaises(ValueError) as e:
      export.build_all_signature_defs(receiver_tensor, None)

    self.assertTrue(str(e.exception).startswith(
        "export_outputs must be a dict"))

  def test_get_timestamped_export_dir(self):
    export_dir_base = tempfile.mkdtemp() + "export/"
    export_dir_1 = export.get_timestamped_export_dir(
        export_dir_base)
    time.sleep(2)
    export_dir_2 = export.get_timestamped_export_dir(
        export_dir_base)
    time.sleep(2)
    export_dir_3 = export.get_timestamped_export_dir(
        export_dir_base)

    # Export directories should be named using a timestamp that is seconds
    # since epoch.  Such a timestamp is 10 digits long.
    time_1 = os.path.basename(export_dir_1)
    self.assertEqual(10, len(time_1))
    time_2 = os.path.basename(export_dir_2)
    self.assertEqual(10, len(time_2))
    time_3 = os.path.basename(export_dir_3)
    self.assertEqual(10, len(time_3))

    self.assertTrue(int(time_1) < int(time_2))
    self.assertTrue(int(time_2) < int(time_3))

  def test_build_all_signature_defs_serving_only(self):
    receiver_tensor = {"input": array_ops.placeholder(dtypes.string)}
    output_1 = constant_op.constant([1.])
    export_outputs = {
        signature_constants.DEFAULT_SERVING_SIGNATURE_DEF_KEY:
            export_output.PredictOutput(outputs=output_1),
        "train": export_output.TrainOutput(loss=output_1),
    }

    signature_defs = export.build_all_signature_defs(
        receiver_tensor, export_outputs)

    expected_signature_defs = {
        "serving_default": signature_def_utils.predict_signature_def(
            receiver_tensor, {"output": output_1})
    }

    self.assertDictEqual(expected_signature_defs, signature_defs)

    signature_defs = export.build_all_signature_defs(
        receiver_tensor, export_outputs, serving_only=False)

    expected_signature_defs.update({
        "train": signature_def_utils.supervised_train_signature_def(
            receiver_tensor, loss={"loss": output_1})
    })

    self.assertDictEqual(expected_signature_defs, signature_defs)


class TensorServingReceiverTest(test_util.TensorFlowTestCase):

  def test_tensor_serving_input_receiver_constructor(self):
    features = constant_op.constant([0])
    receiver_tensors = {
        "example0": array_ops.placeholder(dtypes.string, name="example0"),
        u"example1": array_ops.placeholder(dtypes.string, name="example1"),
    }
    r = export.TensorServingInputReceiver(features, receiver_tensors)
    self.assertTrue(isinstance(r.features, ops.Tensor))
    self.assertTrue(isinstance(r.receiver_tensors, dict))

  def test_tensor_serving_input_receiver_sparse(self):
    features = sparse_tensor.SparseTensor(
        indices=[[0, 0]], values=[1], dense_shape=[1, 1])
    receiver_tensors = {
        "example0": array_ops.placeholder(dtypes.string, name="example0"),
        u"example1": array_ops.placeholder(dtypes.string, name="example1"),
    }
    r = export.TensorServingInputReceiver(features, receiver_tensors)
    self.assertTrue(isinstance(r.features, sparse_tensor.SparseTensor))
    self.assertTrue(isinstance(r.receiver_tensors, dict))

  def test_serving_input_receiver_features_invalid(self):
    receiver_tensors = {
        "example0": array_ops.placeholder(dtypes.string, name="example0"),
        u"example1": array_ops.placeholder(dtypes.string, name="example1"),
    }

    with self.assertRaisesRegexp(ValueError, "features must be defined"):
      export.TensorServingInputReceiver(
          features=None,
          receiver_tensors=receiver_tensors)

    with self.assertRaisesRegexp(ValueError, "feature must be a Tensor"):
      export.TensorServingInputReceiver(
          features={"1": constant_op.constant([1])},
          receiver_tensors=receiver_tensors)

  def test_serving_input_receiver_receiver_tensors_invalid(self):
    features = constant_op.constant([0])

    with self.assertRaisesRegexp(
        ValueError, "receiver_tensors must be defined"):
      export.TensorServingInputReceiver(
          features=features,
          receiver_tensors=None)

    with self.assertRaisesRegexp(
        ValueError, "receiver_tensor keys must be strings"):
      export.TensorServingInputReceiver(
          features=features,
          receiver_tensors={
              1: array_ops.placeholder(dtypes.string, name="example0")})

    with self.assertRaisesRegexp(
        ValueError, "receiver_tensor example1 must be a Tensor"):
      export.TensorServingInputReceiver(
          features=features,
          receiver_tensors={"example1": [1]})


if __name__ == "__main__":
  test.main()

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
"""Tests for the input pipeline ops."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from tensorflow.core.framework import graph_pb2
from tensorflow.python.data.kernel_tests import test_base
from tensorflow.python.data.ops import dataset_ops
from tensorflow.python.platform import test


class DatasetOpsTest(test_base.DatasetTestBase):

  def testAsSerializedGraph(self):
    dataset = dataset_ops.Dataset.range(10)
    with self.cached_session() as sess:
      graph = graph_pb2.GraphDef().FromString(
          sess.run(dataset._as_serialized_graph()))
      self.assertTrue(any([node.op != "RangeDataset" for node in graph.node]))


if __name__ == "__main__":
  test.main()

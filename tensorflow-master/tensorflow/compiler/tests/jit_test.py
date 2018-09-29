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
"""Tests for JIT compilation on the CPU and GPU devices."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import numpy as np

from tensorflow.contrib.compiler import jit
from tensorflow.core.protobuf import config_pb2
from tensorflow.core.protobuf import rewriter_config_pb2
from tensorflow.python.client import session as session_lib
from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import function
from tensorflow.python.framework import ops
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import gradients_impl
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import nn_ops
from tensorflow.python.platform import test

jit_scope = jit.experimental_jit_scope


# Disable rewrites to make sure we don't end up having to update this test
# whenever we implement new ones.
def NoRewriteSessionConfig():
  rewriter_config = rewriter_config_pb2.RewriterConfig(
      disable_model_pruning=True,
      arithmetic_optimization=rewriter_config_pb2.RewriterConfig.OFF,
      dependency_optimization=rewriter_config_pb2.RewriterConfig.OFF,
      function_optimization=rewriter_config_pb2.RewriterConfig.OFF)
  graph_options = config_pb2.GraphOptions(rewrite_options=rewriter_config)
  return config_pb2.ConfigProto(graph_options=graph_options)


def CompiledKernel(fn, *inputs, **kwargs):
  """Execute 'fn' as a compiled XLA kernel, with 'inputs'."""
  name = kwargs.pop("name", None)
  noinline = kwargs.pop("noinline", None)

  @function.Defun(func_name=name, noinline=noinline, compiled=True)
  def Compiled(*args):
    return fn(*args)

  return Compiled(*inputs)


def RunMetadataLabels(run_metadata):
  """Returns all labels in run_metadata."""
  labels = []
  for dev_stats in run_metadata.step_stats.dev_stats:
    for node_stats in dev_stats.node_stats:
      labels.append(node_stats.timeline_label)
  return labels


def InLabels(labels, substr):
  """Returns true iff one of the labels contains substr."""
  return any([substr in x for x in labels])


def MetadataHasXlaOp(run_metadata):
  """Returns true if there are XlaRun kernels in run_metadata's timeline."""

  # TODO(phawkins): find a less hacky way to test whether a kernel ran.
  return InLabels(RunMetadataLabels(run_metadata), "XlaRun")


class JitLaunchTest(test.TestCase):

  # Evaluates 'fn' on 'args' both directly and as a compiled XLA kernel.
  # Verifies that the outputs match and that XLA was invoked. 'fn' must take
  # the same number of tensors as arguments that are in 'args', and must return
  # a tuple of output tensors.
  #
  # If 'require_kernel_launch' is True, then we verify that an XlaCompile/XlaRun
  # node actually ran. However, it is sometimes possible for XlaCompile/XlaRun
  # ops to be constant-folded away, so the check is optional.
  def _compare(self, fn, args, require_kernel_launch=True, noinline=None):
    with session_lib.Session(config=NoRewriteSessionConfig()) as sess:
      placeholders = []
      feeds = {}
      for arg in args:
        placeholder = array_ops.placeholder(
            dtypes.as_dtype(arg.dtype), list(arg.shape))
        placeholders.append(placeholder)
        feeds[placeholder] = arg

      compiled_op = CompiledKernel(fn, *placeholders, noinline=noinline)
      direct_op = fn(*placeholders)

      run_metadata = config_pb2.RunMetadata()
      compiled = sess.run(compiled_op,
                          feeds,
                          run_metadata=run_metadata,
                          options=config_pb2.RunOptions(
                              trace_level=config_pb2.RunOptions.FULL_TRACE))
      print("Compiled Result {}".format(compiled))

      if require_kernel_launch:
        self.assert_(MetadataHasXlaOp(run_metadata))

        direct = sess.run(direct_op, feeds)
        print("Direct Result {}".format(direct))

        if (isinstance(compiled, (tuple, list)) and
            (isinstance(direct, (tuple, list)))):
          for (x, y) in zip(compiled, direct):
            self.assertAllClose(x, y, rtol=1e-1)
        else:
          self.assertAllClose(compiled, direct, rtol=1e-2)

  def testNoOutputs(self):
    with session_lib.Session() as sess:

      # Check that calling the result as a compiled kernel doesn't crash.
      @function.Defun(compiled=True)
      def KernelWithNoOutputs():
        a = constant_op.constant(100)  # pylint: disable=unused-variable

      call = KernelWithNoOutputs()  # pylint: disable=assignment-from-no-return
      sess.run(call, {})

  def testAliasing(self):
    """Regression test for compiled functions that return an aliased buffer.

       XLA returns aliased buffers if outputs are identical. Tests that
       we handle that case.
    """

    def AddOnceReturnTwice(x):
      y = math_ops.add(x, x)
      return y, y

    # Exercises compiling a function (say, Foo) which calls another function
    # (say, Bar) which is not inlined. When the compiler compiles Foo, it needs
    # to symbolically execute Bar correctly regardless of whether Bar is inlined
    # or not.

    # TODO(b/36139787): Re-enable this test when noinline works again.
    # Tests compiled=True and noinline=True.
    # self._compare(
    #     AddOnceReturnTwice, [np.array(
    #         [[[0.5, -1.0]]], dtype=np.float32)],
    #     noinline=True)

    # Tests compiled=True and noinline=False.
    self._compare(
        AddOnceReturnTwice, [np.array(
            [[[0.5, -1.0]]], dtype=np.float32)],
        noinline=False)

  def testOneConstOutput(self):
    """Test consisting of a single constant return value."""

    def OneConstOutput():
      return constant_op.constant([-3, 44, 99])

    self._compare(OneConstOutput, [], require_kernel_launch=False)

  def testConstZeroElementOutput(self):
    """Test consisting of a constant zero element return value."""

    def ConstZeroElementOutput():
      return array_ops.fill([7, 0], 3.0)

    self._compare(ConstZeroElementOutput, [], require_kernel_launch=False)

  def testSomeConstOutputs(self):
    """Test kernels that return a mixture of const and non-const outputs."""

    def SomeConstOutputs(x):
      return constant_op.constant(
          [-2, 7]), array_ops.identity(x), constant_op.constant(3.5)

    self._compare(
        SomeConstOutputs, [np.array(
            [[1, 2, 3], [4, 5, 6]], dtype=np.float32)])

  def testInt32Input(self):
    """Test an int32-typed input.

       On a GPU, int32 tensors will be placed in host memory.
    """

    def AddToSelf(x):
      return math_ops.add(x, x)

    self._compare(AddToSelf, [np.array([7, 1, 3], dtype=np.int32)])

  def testMandatoryConstantInput(self):
    """Tests an operator that has a mandatory-constant shape input."""

    def FillWithFloat(x):
      return array_ops.fill(x, 9.5)

    self._compare(FillWithFloat, [np.array([3, 2], dtype=np.int32)])

  def testMnistForwardFunc(self):
    """Compute inference function from MNIST beginners tutorial."""
    batch_size = 16
    image_size = 28 * 28
    num_classes = 10

    # Define a TensorFlow function to compute the forward pass.
    def MnistForward(w, b, x):
      return nn_ops.softmax(math_ops.matmul(x, w) + b)

    w = np.random.random_sample((image_size, num_classes)).astype(np.float32)
    b = np.random.random_sample((num_classes)).astype(np.float32)
    x = np.random.random_sample((batch_size, image_size)).astype(np.float32)
    self._compare(MnistForward, [w, b, x])

  def testExplicitMarking(self):
    """Test explicit marking of operators to compile."""
    batch_size = 16
    image_size = 28 * 28
    num_classes = 10

    with ops.Graph().as_default():
      x = array_ops.placeholder(dtypes.float32)
      w = array_ops.placeholder(dtypes.float32)
      b = array_ops.placeholder(dtypes.float32)
      with jit_scope():
        y1 = math_ops.matmul(x, w)
      y2 = math_ops.add(y1, b)
      with jit_scope():
        y = math_ops.square(y2)

      dw = np.random.random_sample((image_size, num_classes)).astype(np.float32)
      db = np.random.random_sample((num_classes)).astype(np.float32)
      dx = np.random.random_sample((batch_size, image_size)).astype(np.float32)
      with session_lib.Session() as sess:
        run_metadata = config_pb2.RunMetadata()
        output = sess.run(y, {x: dx,
                              w: dw,
                              b: db},
                          run_metadata=run_metadata,
                          options=config_pb2.RunOptions(
                              trace_level=config_pb2.RunOptions.FULL_TRACE))

        # TODO(phawkins): really we would like to test that there were exactly
        # two kernel launches. However, we have no reliable way to determine
        # that.
        self.assert_(MetadataHasXlaOp(run_metadata))

        expected = np.square(np.dot(dx, dw) + db)
        self.assertAllClose(expected, output, rtol=1e-1)


class XlaCompilationTest(test.TestCase):
  """Tests for auto-compilation on CPU/GPU devices."""

  def testReshape(self):
    """Tests an operator with compile-time constant and non-constant inputs."""

    with self.test_session(config=NoRewriteSessionConfig()) as sess:
      x = array_ops.placeholder(dtypes.float32)
      y = array_ops.placeholder(dtypes.int32)
      with jit_scope():
        # Reshape's first argument is non-constant in the JIT, but its second
        # (shape) argument will be treated as a compile-time constant for
        # each JIT compilation.
        # We do not use a tf.const() argument since we want to ensure the
        # shape is still a run-time argument to the JIT, and not
        # statically known as part of the JIT compilation's input graph.
        z = array_ops.reshape(x, y)
      run_metadata = config_pb2.RunMetadata()
      out = sess.run(z,
                     {x: np.array([1, 2, 3, 4, 5, 6], np.float32),
                      y: [-1, 3]},
                     run_metadata=run_metadata,
                     options=config_pb2.RunOptions(
                         trace_level=config_pb2.RunOptions.FULL_TRACE))
      self.assert_(MetadataHasXlaOp(run_metadata))
      self.assertAllClose(np.array([[1, 2, 3], [4, 5, 6]], np.float32), out)

  def testIgnoredArguments(self):
    """Tests that JIT computations can ignore formal parameters."""

    with self.test_session(config=NoRewriteSessionConfig()) as sess:
      x = array_ops.placeholder(dtypes.int32)
      y = array_ops.placeholder(dtypes.int32)
      with jit_scope():
        z = math_ops.add(x, x)
        w = math_ops.add(y, y)
        # Pulls 'w' into the same compilation via control dependencies.
        with ops.control_dependencies([w]):
          n = control_flow_ops.no_op()
        with ops.control_dependencies([n]):
          t = math_ops.add(z, z)

      run_metadata = config_pb2.RunMetadata()
      out = sess.run(t, {x: np.int32(7),
                         y: np.int32(404)},
                     run_metadata=run_metadata,
                     options=config_pb2.RunOptions(
                         trace_level=config_pb2.RunOptions.FULL_TRACE))
      self.assert_(MetadataHasXlaOp(run_metadata))
      self.assertAllClose(28, out)

  def testLoops(self):
    """Tests that compilation accepts computations containing loops."""

    with self.test_session(config=NoRewriteSessionConfig()) as session:
      x = array_ops.placeholder(dtypes.float32)
      with jit_scope():
        c = lambda i, _: math_ops.less(i, 5)
        b = lambda i, x: (i + 1, x * 2.0 + 1.0)
        _, y = control_flow_ops.while_loop(c, b, (constant_op.constant(0), x))

      run_metadata = config_pb2.RunMetadata()
      result = session.run(y, {x: np.float32(2)},
                           run_metadata=run_metadata,
                           options=config_pb2.RunOptions(
                               trace_level=config_pb2.RunOptions.FULL_TRACE))
      self.assert_(MetadataHasXlaOp(run_metadata))
      self.assertAllClose(result, np.float32(95), rtol=1e-1)

  def testCond(self):
    """Tests that compilation handles switch operators."""

    with self.test_session(config=NoRewriteSessionConfig()) as session:
      x = array_ops.placeholder(dtypes.float32)
      y = array_ops.placeholder(dtypes.float32)
      c = array_ops.placeholder(dtypes.bool)
      with jit_scope():
        z = x + 1.0
        w = control_flow_ops.cond(c, lambda: z, lambda: y)
        t = math_ops.add(z, w)

      # If JIT compilation chooses to cluster z and t, then execution will
      # deadlock.

      run_metadata = config_pb2.RunMetadata()
      result = session.run(t, {x: np.float32(2),
                               y: np.float32(4),
                               c: True},
                           run_metadata=run_metadata,
                           options=config_pb2.RunOptions(
                               trace_level=config_pb2.RunOptions.FULL_TRACE))
      self.assert_(MetadataHasXlaOp(run_metadata))
      self.assertAllClose(result, np.float32(6), rtol=1e-1)

  def testNestedFunction(self):
    g = ops.Graph()
    with g.as_default():

      @function.Defun(compiled=True)
      def Bar(x, y):
        return x + 2 * y

      @function.Defun(compiled=True)
      def Foo(x):
        return Bar(x * x, x * x * x)

      @function.Defun()
      def Entry(x):
        return Foo(x)

      inp = array_ops.placeholder(dtypes.float32)
      out = Entry(inp)

    with self.test_session(
        config=NoRewriteSessionConfig(), graph=g, use_gpu=True) as sess:
      run_metadata = config_pb2.RunMetadata()
      val = sess.run(out,
                     feed_dict={inp: [2., 10.]},
                     run_metadata=run_metadata,
                     options=config_pb2.RunOptions(
                         trace_level=config_pb2.RunOptions.FULL_TRACE))
      self.assertAllClose(val, [20., 2100.])

  def testLoopDeadlock(self):
    """Regression test for bug that caused deadlocks in graphs with loops."""

    with self.test_session(config=NoRewriteSessionConfig()) as session:
      x = array_ops.placeholder(dtypes.float32)
      with jit_scope():
        y = x + 1.0
        c = lambda i, _x, _y: math_ops.less(i, 5)
        b = lambda i, x, _y: (i + 1, x * 2.0 + 1.0, x - 3.0)
        _, _, w = control_flow_ops.while_loop(c, b,
                                              (constant_op.constant(0), y, x))
        u = w + y
      result = session.run(u, {x: np.float32(2)})
      self.assertAllClose(result, np.float32(63), rtol=1e-1)

  def testGradient(self):
    """Tests that the backprop function is properly compiled."""

    def _Run(compiled):

      @function.Defun(compiled=compiled)
      def Forward(x):
        return math_ops.log(x)

      g = ops.Graph()
      with g.as_default():
        x = array_ops.placeholder(dtypes.float32)
        y = Forward(x)
        dx, = gradients_impl.gradients(y, [x], 1.0)

      cfg = NoRewriteSessionConfig()
      cfg.graph_options.optimizer_options.opt_level = (
          config_pb2.OptimizerOptions.L1)
      cfg.graph_options.optimizer_options.do_function_inlining = True
      with session_lib.Session(graph=g, config=cfg) as sess:
        run_metadata = config_pb2.RunMetadata()
        dx_val = sess.run(dx,
                          feed_dict={x: 100.},
                          run_metadata=run_metadata,
                          options=config_pb2.RunOptions(
                              trace_level=config_pb2.RunOptions.FULL_TRACE))
      self.assertAllClose(dx_val, 0.01)
      return RunMetadataLabels(run_metadata)

    # SymGrad[f=log(x)](x, dy) = 1/x * dy
    #
    # Note: we don't need to compute log(x) for dx due to graph pruning.

    # Do not compile the backprop. We should see one Reciprocal and one Mul.
    labels = _Run(compiled=False)
    self.assertFalse(InLabels(labels, "Log"))
    self.assertTrue(InLabels(labels, "Reciprocal"))
    self.assertTrue(InLabels(labels, "Mul"))
    self.assertFalse(InLabels(labels, "XlaCompile"))
    self.assertFalse(InLabels(labels, "XlaRun"))

    # Compile the backprop. One XlaCompile/XlaRun pair.
    labels = _Run(compiled=True)
    self.assertFalse(InLabels(labels, "Log"))
    self.assertFalse(InLabels(labels, "Reciprocal"))
    self.assertFalse(InLabels(labels, "Mul"))
    self.assertTrue(InLabels(labels, "XlaCompile"))
    self.assertTrue(InLabels(labels, "XlaRun"))


class ElementWiseFusionTest(test.TestCase):

  # Runs a simple test with the input jit_level and fusion_only flag.
  def simpleTest(self, arg0, arg1, global_jit_level):
    config = config_pb2.ConfigProto()
    config.graph_options.optimizer_options.global_jit_level = global_jit_level

    with session_lib.Session(config=config) as sess:
      a1 = array_ops.placeholder(dtypes.float32, [2, 2], name="a1")
      a2 = array_ops.placeholder(dtypes.float32, [2, 2], name="a2")
      # Two element-wise ops. We need at least two ops since single
      # element clusters are not passed to XLA in fusion_only mode.
      a3 = a1 * a2
      a4 = a3 + a1
      # A matmul to break XLA clustering.
      a5 = math_ops.matmul(a4, a1)
      # Two more element-wise ops.
      a6 = a5 - a4
      a7 = a6 + a2

      run_metadata = config_pb2.RunMetadata()
      output = sess.run(
          a7, {
              a1: arg0,
              a2: arg1
          },
          run_metadata=run_metadata,
          options=config_pb2.RunOptions(
              trace_level=config_pb2.RunOptions.FULL_TRACE))

      labels = RunMetadataLabels(run_metadata)

      xla_compile_count = sum("XlaCompile(" in x for x in labels)
      xla_run_count = sum("XlaRun(" in x for x in labels)
      self.assertEqual(xla_compile_count, xla_run_count)

      return output, xla_run_count

  def testElementWiseClustering(self):
    arg0 = np.random.rand(2, 2).astype(np.float32)
    arg1 = np.random.rand(2, 2).astype(np.float32)
    os.environ["TF_XLA_FLAGS"] = (
        "--tf_xla_fusion_only=true "
        "--tf_xla_cpu_global_jit " + os.environ.get("TF_XLA_FLAGS", ""))
    tf_op, tf_count = self.simpleTest(arg0, arg1,
                                      config_pb2.OptimizerOptions.OFF)
    self.assertEqual(0, tf_count)

    tfef_op, tfef_count = self.simpleTest(arg0, arg1,
                                          config_pb2.OptimizerOptions.ON_1)
    self.assertEqual(2, tfef_count)

    self.assertAllClose(tf_op, tfef_op, rtol=1e-1)


if __name__ == "__main__":
  test.main()

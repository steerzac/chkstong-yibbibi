/* Copyright 2018 The TensorFlow Authors. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
==============================================================================*/

// Contains utilities for launching compiled XLA kernels for a KernelContext.

#ifndef TENSORFLOW_COMPILER_JIT_XLA_LAUNCH_UTIL_H_
#define TENSORFLOW_COMPILER_JIT_XLA_LAUNCH_UTIL_H_

#include "tensorflow/compiler/jit/xla_compilation_cache.h"
#include "tensorflow/compiler/jit/xla_tensor.h"
#include "tensorflow/compiler/tf2xla/xla_compiler.h"
#include "tensorflow/compiler/xla/client/local_client.h"
#include "tensorflow/compiler/xla/service/device_memory_allocator.h"
#include "tensorflow/compiler/xla/service/owning_device_memory.h"
#include "tensorflow/core/framework/allocation_description.pb.h"
#include "tensorflow/core/framework/tensor.h"
#include "tensorflow/core/framework/types.h"
#include "tensorflow/core/kernels/variable_ops.h"
#include "tensorflow/core/lib/core/status.h"
#include "tensorflow/core/lib/gtl/array_slice.h"

namespace tensorflow {
class XlaAllocator;

// Takes a snapshot of the values of resource variable arguments, whose
// indices are specified in `variables` argument. We snapshot tensors that back
// resource variables since concurrent updates may modify the shape, and it is
// important that the shapes used for compilation match the true shapes of the
// buffers.
//
// Returns a map of TensorFlow argument index to resource variable. If a
// resource variable is not initialized, the corresponding OptionalTensor
// will have its `present` field set to false.
std::map<int, OptionalTensor> SnapshotResourceVariables(
    OpKernelContext* ctx, absl::Span<const int> variables);

// Adapter class that wraps a Tensorflow allocator as an XLA allocator.
// Assumes that the Tensorflow allocator permits asynchronous deallocation:
// see comment on `AllowsAsynchronousDeallocation()`.
class XlaAllocator : public xla::DeviceMemoryAllocator {
 public:
  XlaAllocator(const se::Platform* platform, Allocator* wrapped);
  ~XlaAllocator() override;
  xla::StatusOr<xla::OwningDeviceMemory> Allocate(
      int device_ordinal, uint64 size, bool retry_on_failure) override;
  Status Deallocate(int device_ordinal, se::DeviceMemoryBase mem) override;

  // The Tensorflow BFC allocator used on GPU allows host-side deallocation
  // before GPU execution takes place. Tensorflow uses the ordering of the main
  // compute stream to enforce a happens-before relationship between a memory
  // allocation and code that reuses the same memory. If Tensorflow adds
  // support for multiple GPU streams or allocators with different ordering
  // requirements, this code may need to change.
  // (This attribute has no effect on CPU.)
  bool AllowsAsynchronousDeallocation() const override { return true; }

 private:
  Allocator* wrapped_;
};

// Helper class to perform the marshalling of TensorFlow inputs and outputs to
// ShapedBuffers suitable for passing to an XLA computation.
class XlaComputationLaunchContext {
 public:
  // Create a new launch context. 'allocate_xla_tensors' is true if allocated
  // output tensors and variables are always XlaTensors. If false they are
  // assumed to be "normal" device pointers.
  // If 'use_multiple_streams' is true, tensors may be defined and used on
  // multiple streams and so se::Events must be defined and waited for. If
  // 'use_multiple_streams' is true, 'allocate_xla_tensors' must also be true
  // because we track inter-stream dependencies through events inside XlaTensor
  // objects.
  XlaComputationLaunchContext(xla::LocalClient* client,
                              xla::DeviceMemoryAllocator* xla_allocator,
                              bool allocate_xla_tensors,
                              bool use_multiple_streams);

  // Add all inputs within `ctx` as XLA arguments (returned by arguments()).
  // `variables` is a map from TensorFlow argument number to resource variable.
  //
  // Assumes that the first `missing_ctx_input_prefix` inputs to the kernel are
  // missing and adjusts input indices accordingly.  All elements in kernel's
  // input_mapping must be greater than or equal to `missing_ctx_input_prefix`
  // (in other words, no inputs actually required by the kernel can be missing).
  void PopulateInputs(OpKernelContext* ctx,
                      const XlaCompiler::CompilationResult* kernel,
                      const std::map<int, OptionalTensor>& variables,
                      int missing_ctx_input_prefix);

  // Given the XLA output in `output`, populate all outputs of `ctx`.
  //
  // Assumes that the first `missing_ctx_input_prefix` inputs to the kernel are
  // missing and adjusts input indices accordingly.
  Status PopulateOutputs(OpKernelContext* ctx,
                         const XlaCompiler::CompilationResult* kernel,
                         xla::ScopedShapedBuffer output,
                         int missing_ctx_input_prefix);

  // Return the argument list. Only valid after PopulateInputs() has been
  // called.
  const std::vector<xla::ShapedBuffer*>& arguments() const { return arg_ptrs_; }

 private:
  xla::LocalClient* client_;
  xla::DeviceMemoryAllocator* xla_allocator_;
  bool allocate_xla_tensors_;
  bool use_multiple_streams_;
  std::vector<std::unique_ptr<xla::ShapedBuffer>> arg_buffers_;
  std::vector<xla::ShapedBuffer*> arg_ptrs_;
};

// A simple TensorBuffer implementation that allows us to create Tensors that
// take ownership of pre-allocated memory.
class XlaTensorBuffer : public TensorBuffer {
 public:
  XlaTensorBuffer(const void* ptr, size_t expected_size, size_t actual_size,
                  Allocator* allocator)
      : expected_size_(expected_size),
        actual_size_(actual_size),
        allocator_(allocator) {
    data_ = const_cast<void*>(ptr);
  }

  ~XlaTensorBuffer() override {
    if (data_) {
      allocator_->DeallocateRaw(data_);
    }
  }

  void* data() const override { return data_; }
  size_t size() const override { return expected_size_; }

  TensorBuffer* root_buffer() override { return this; }

  void FillAllocationDescription(AllocationDescription* proto) const override {
    proto->set_allocated_bytes(actual_size_);
  }

  static Tensor MakeTensor(DataType dtype, const TensorShape& shape,
                           se::DeviceMemoryBase buffer, Allocator* allocator) {
    size_t expected_size = shape.num_elements() * DataTypeSize(dtype);
    auto* tensor_buffer = new XlaTensorBuffer(buffer.opaque(), expected_size,
                                              buffer.size(), allocator);
    Tensor t(dtype, shape, tensor_buffer);
    tensor_buffer->Unref();
    return t;
  }

 private:
  void* data_;
  size_t expected_size_;
  size_t actual_size_;
  Allocator* allocator_;
};

// Exposed in this header file for microbenchmarking purposes, but this is an
// internal implementation detail.
namespace internal {
// Return the 'index''th subtree of the given ShapedBuffer as a
// ScopedShapedBuffer. The returned ScopedShapedBuffer takes ownership of the
// subtree, and sets the input's buffer pointers to nullptr for the subtree.
xla::ScopedShapedBuffer ExtractSubShapedBuffer(
    xla::ShapedBuffer* shaped_buffer, int index,
    xla::DeviceMemoryAllocator* allocator);
}  // namespace internal

}  // namespace tensorflow

#endif  // TENSORFLOW_COMPILER_JIT_XLA_LAUNCH_UTIL_H_

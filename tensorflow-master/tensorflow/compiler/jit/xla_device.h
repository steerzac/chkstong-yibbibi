/* Copyright 2017 The TensorFlow Authors. All Rights Reserved.

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

// The XlaDevice executes a TensorFlow graph using the XLA linear algebra
// runtime.
//
// Operators assigned to an XlaDevice are compiled into XLA computations.
// Tensors on an XlaDevice are thin wrappers around XLA ScopedShapedBuffers.
//
// XlaDevice is instantiated separately for each XLA backend (e.g., CPU or GPU),
// under different names (e.g., XLA_CPU or XLA_GPU).

#ifndef TENSORFLOW_COMPILER_JIT_XLA_DEVICE_H_
#define TENSORFLOW_COMPILER_JIT_XLA_DEVICE_H_

#include "tensorflow/compiler/jit/xla_device_context.h"
#include "tensorflow/compiler/jit/xla_tensor.h"
#include "tensorflow/compiler/tf2xla/xla_compiler.h"
#include "tensorflow/compiler/tf2xla/xla_op_registry.h"
#include "tensorflow/compiler/xla/client/local_client.h"
#include "tensorflow/core/common_runtime/device_factory.h"
#include "tensorflow/core/common_runtime/local_device.h"
#include "tensorflow/core/framework/allocator.h"
#include "tensorflow/core/framework/device_base.h"
#include "tensorflow/core/framework/node_def_builder.h"
#include "tensorflow/core/framework/op_kernel.h"
#include "tensorflow/core/framework/resource_mgr.h"
#include "tensorflow/core/framework/tensor.h"
#include "tensorflow/core/framework/types.h"
#include "tensorflow/core/lib/core/status.h"
#include "tensorflow/core/platform/mutex.h"
#include "tensorflow/core/platform/stream_executor_no_cuda.h"

namespace tensorflow {

class XlaDevice : public LocalDevice {
 public:
  // Given a tensor, sets `xla::Shape*` the shape of tensor's representation
  // on device, fully padded. On error, the contents of `xla::Shape*`
  // are undefined.
  typedef std::function<Status(const Tensor&, xla::Shape*)> PaddedShapeFn;

  // Wrapper class to store metadata about the XlaDevice, where it can be
  // retrieved e.g., when lazily creating the XlaCompilationCache device.
  class Metadata {
   public:
    Metadata(int device_ordinal, se::Platform* platform,
             const DeviceType& device_type,
             XlaCompiler::ShapeRepresentationFn shape_representation_fn,
             PaddedShapeFn padded_shape_fn, bool use_multiple_streams);

    // The index of the device on this host.
    int device_ordinal() const;

    se::Platform* platform() const;
    xla::LocalClient* client() const;
    const DeviceType& jit_device_type() const;
    const XlaCompiler::ShapeRepresentationFn& shape_representation_fn() const {
      return shape_representation_fn_;
    }
    const PaddedShapeFn& padded_shape_fn() const { return padded_shape_fn_; }

    bool UseMultipleStreams() const { return use_multiple_streams_; }

   private:
    const int device_ordinal_;
    const DeviceType device_type_;
    se::Platform* platform_;  // Not owned.
    XlaCompiler::ShapeRepresentationFn shape_representation_fn_;
    PaddedShapeFn padded_shape_fn_;
    const bool use_multiple_streams_;

    TF_DISALLOW_COPY_AND_ASSIGN(Metadata);
  };

  // Sets `*metadata` to the XlaDevice Metadata in the XLA device used by `ctx`.
  static Status GetMetadata(OpKernelContext* ctx, const Metadata** metadata);

  // Sets `*metadata` to the XlaDevice Metadata in the XLA device used by `ctx`.
  static Status GetMetadata(OpKernelConstruction* ctx,
                            const Metadata** metadata);

  // Factory function. 'platform_name' is the name of the XLA platform.
  // 'device_name' is the name of the Tensorflow device to create.
  // 'jit_device_name' is the name of the corresponding JIT device.
  // 'transfer_as_literal' is true if device<->host transfers must be done using
  // XLA's TransferLiteral{To,From}Device interface. If false, we can use
  // ThenMemcpy instead.
  // If 'use_multiple_streams' is true, we create separate streams for
  // host-to-device and device-to-host communication.
  // If padded_shape_fn is empty, a default implementation that returns
  // the on-host shape is used.
  static Status Create(
      const string& platform_name, const string& device_name,
      int device_ordinal, const string& jit_device_name,
      const SessionOptions& options, const string& name_prefix,
      const XlaOpRegistry::DeviceRegistration& registration,
      bool transfer_as_literal, bool use_multiple_streams,
      const XlaCompiler::ShapeRepresentationFn& shape_representation_fn,
      const PaddedShapeFn& padded_shape_fn, std::unique_ptr<XlaDevice>* device);

  // Creates a new XLA Device.
  // If padded_shape_fn is empty, a default implementation that returns
  // the logical on-device shape without padding is used.
  XlaDevice(const SessionOptions& options, const DeviceAttributes& attrs,
            int device_ordinal, const DeviceType& jit_device_name,
            se::Platform* platform, bool transfer_as_literal,
            bool use_multiple_streams,
            const XlaCompiler::ShapeRepresentationFn& shape_representation_fn,
            const PaddedShapeFn& padded_shape_fn);
  ~XlaDevice() override;

  Allocator* GetAllocator(AllocatorAttributes attr) override
      LOCKS_EXCLUDED(mu_);
  void Compute(OpKernel* op_kernel, OpKernelContext* context) override;
  void ComputeAsync(AsyncOpKernel* op_kernel, OpKernelContext* context,
                    AsyncOpKernel::DoneCallback done) override;
  Status Sync() override;

  Status FillContextMap(const Graph* graph,
                        DeviceContextMap* device_context_map) override
      LOCKS_EXCLUDED(mu_);

  Status MakeTensorFromProto(const TensorProto& tensor_proto,
                             const AllocatorAttributes alloc_attrs,
                             Tensor* tensor) override LOCKS_EXCLUDED(mu_);

  const Metadata& metadata() { return xla_metadata_; }

  // Ensures the DeviceContext associated with this XlaDevice is created and
  // valid (i.e. all streams are ok). If any state is not valid, a new
  // DeviceContext will be created.
  //
  // TODO(b/111859745): The Eager context needs to call this method to recover
  // from failures.
  Status EnsureDeviceContextOk() LOCKS_EXCLUDED(mu_);

  // Instructs this XlaDevice to set a GpuDeviceInfo, which holds extra
  // information for GPU and TPU devices.
  Status UseGpuDeviceInfo() LOCKS_EXCLUDED(mu_);

  // Instructs this XlaDevice to return 'sync_on_completion' for
  // RequiresSyncOnCompletion().
  void SetRequiresSyncOnCompletion(bool sync_on_completion) LOCKS_EXCLUDED(mu_);

  bool RequiresSyncOnCompletion() const override LOCKS_EXCLUDED(mu_);

 private:
  xla::LocalClient* client() const;
  Allocator* GetAllocatorLocked(AllocatorAttributes attr)
      EXCLUSIVE_LOCKS_REQUIRED(mu_);
  Status EnsureStreamOkLocked(xla::Backend* backend, const string& name,
                              std::shared_ptr<se::Stream>* stream,
                              bool* stream_was_changed)
      EXCLUSIVE_LOCKS_REQUIRED(mu_);
  xla::StatusOr<XlaDeviceContext*> GetDeviceContextLocked()
      EXCLUSIVE_LOCKS_REQUIRED(mu_);

  static Status GetMetadataFromDevice(DeviceBase* device,
                                      const XlaDevice::Metadata** metadata);

  mutable mutex mu_;
  // The metadata of this XlaDevice.
  const Metadata xla_metadata_;
  // Which hardware device in the client's platform this XlaDevice controls.
  const int device_ordinal_;
  // The name of the device that is used to compile Ops for this XlaDevice.
  const DeviceType jit_device_name_;
  // The platform for this device.
  se::Platform* const platform_;  // Not owned.
  // Memory allocator associated with this device.
  Allocator* xla_allocator_ GUARDED_BY(mu_) = nullptr;  // Not owned.
  // Stream associated with this device. Operations enqueued on this
  // stream are executed on the device. Operations include data
  // copying back and forth between CPU and the device, and
  // computations enqueued by XLA.
  std::shared_ptr<se::Stream> stream_ GUARDED_BY(mu_);
  // If false, only stream_ is valid and all computation and transfers use
  // stream_. If true, computation is performed by stream_ and transfers are
  // performed by host_to_device/device_to_host_stream.
  const bool use_multiple_streams_;
  // If use_multiple_streams_, host to device transfers are performed using this
  // stream.
  std::shared_ptr<se::Stream> host_to_device_stream_ GUARDED_BY(mu_);
  // If use_multiple_streams_, device to host transfers are performed using this
  // stream.
  std::shared_ptr<se::Stream> device_to_host_stream_ GUARDED_BY(mu_);
  // Must we use XLA's transfer manager for correct host<->device transfers? if
  // false, we can use ThenMemcpy() instead.
  const bool transfer_as_literal_;
  const XlaCompiler::ShapeRepresentationFn shape_representation_fn_;

  // The device context accessed by all users of the XlaDevice, set by calls to
  // EnsureDeviceContextOk. If gpu_device_info_ is non-null, this pointer is
  // also filled in to that struct. XlaDeviceContext is a ref-counted object.
  XlaDeviceContext* device_context_ GUARDED_BY(mu_) = nullptr;

  // Holds extra information for GPU and TPU devices, e.g. the device context.
  bool use_gpu_device_info_ GUARDED_BY(mu_) = false;
  std::unique_ptr<GpuDeviceInfo> gpu_device_info_ GUARDED_BY(mu_);

  // Thread pool used for running closures
  std::unique_ptr<thread::ThreadPool> thread_pool_;

  // True if the device requires XlaDevice::Sync to be called on completion
  // regardless of status.
  bool sync_on_completion_ GUARDED_BY(mu_) = false;
};

// Builds OpKernel registrations on 'device' for the JIT operators
// registered on 'jit_device'. Returns ownership of a XlaDeviceOpRegistrations
// object that encapsulates the kernel registrations.
struct XlaDeviceOpRegistrations {
  std::vector<std::unique_ptr<kernel_factory::OpKernelRegistrar>>
      op_kernel_registrars;
};
XlaDeviceOpRegistrations* RegisterXlaDeviceKernels(const char* device,
                                                   const char* jit_device);

}  // namespace tensorflow

#endif  // TENSORFLOW_COMPILER_JIT_XLA_DEVICE_H_

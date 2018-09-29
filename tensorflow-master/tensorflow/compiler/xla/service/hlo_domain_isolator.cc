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

#include "tensorflow/compiler/xla/service/hlo_domain_isolator.h"

#include "tensorflow/compiler/xla/map_util.h"
#include "tensorflow/compiler/xla/service/hlo_computation.h"
#include "tensorflow/compiler/xla/service/hlo_graph_dumper.h"
#include "tensorflow/compiler/xla/service/hlo_opcode.h"
#include "tensorflow/compiler/xla/types.h"

namespace xla {

class HloDomainIsolator::RunContext {
 public:
  RunContext(HloModule* module, HloDomainIsolator* isolator)
      : module_(module), isolator_(isolator) {}

  StatusOr<bool> Run();

 private:
  HloModule* module_;
  HloDomainIsolator* isolator_;
};

StatusOr<bool> HloDomainIsolator::RunContext::Run() {
  hlo_graph_dumper::MaybeDumpHloModule(*module_, "Before Domain Isolator");

  int64 added_domains = 0;
  for (HloComputation* computation : module_->computations()) {
    // Walk in post order and place all the required kDomain instructions.
    for (HloInstruction* instruction :
         computation->MakeInstructionPostOrder()) {
      if (instruction->opcode() == HloOpcode::kDomain) {
        continue;
      }
      for (HloInstruction* operand : instruction->unique_operands()) {
        // When applying multiple domains, we could end up stacking more than
        // one in one edge, so here we want to build the effective
        // (kDomain-less) instruction->operand edge.
        HloInstruction* root = operand;
        while (root->opcode() == HloOpcode::kDomain) {
          root = root->mutable_operand(0);
        }
        // Check whether a kDomain is necessary between instruction and operand.
        HloInstruction* domain =
            isolator_->creator_(instruction, root, operand);
        if (domain != nullptr) {
          VLOG(4) << "New domain: " << domain->ToString();
          TF_RETURN_IF_ERROR(operand->ReplaceUseWith(instruction, domain));
          ++added_domains;
        }
      }
    }
  }
  VLOG(3) << "Added " << added_domains << " kDomain instructions";
  if (added_domains > 0) {
    hlo_graph_dumper::MaybeDumpHloModule(*module_, "After Domain Isolator");
  }
  return added_domains > 0;
}

HloDomainIsolator::HloDomainIsolator(DomainCreator creator)
    : creator_(std::move(creator)) {}

StatusOr<bool> HloDomainIsolator::Run(HloModule* module) {
  RunContext run_context(module, this);
  return run_context.Run();
}

}  // namespace xla

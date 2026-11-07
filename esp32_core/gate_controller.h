#pragma once
#include <stdint.h>

// Logical targets only: without position feedback, PWM is not proof of motion.
class GateController {
 public:
  bool update(bool detected, uint32_t now) {
    bool changed = false;
    if (!ready_) { ready_ = true; changed = true; }
    if (!automatic_) return changed;
    if (detected) {
      changed = changed || !opened_ || waiting_;
      opened_ = true;
      waiting_ = false;
    } else if (opened_) {
      if (!waiting_) { clearSince_ = now; waiting_ = true; changed = true; }
      if (static_cast<uint32_t>(now - clearSince_) >= 3000) {
        opened_ = false;
        waiting_ = false;
        changed = true;
      }
    }
    return changed;
  }

  void restoreMode(bool automatic) { automatic_ = automatic; }
  bool setMode(bool automatic, uint32_t revision, bool detected, uint32_t now) {
    if (!ready_ || revision <= revision_) return false;
    revision_ = revision;
    automatic_ = automatic;
    waiting_ = false;
    update(detected, now);
    return true;
  }
  bool setTarget(bool opened, uint32_t revision) {
    if (!ready_ || automatic_ || revision <= revision_) return false;
    revision_ = revision;
    opened_ = opened;
    waiting_ = false;
    return true;
  }
  bool ready() const { return ready_; }
  bool automatic() const { return automatic_; }
  bool opened() const { return opened_; }
  uint32_t revision() const { return revision_; }
  uint32_t remaining(uint32_t now) const {
    if (!waiting_) return 0;
    const uint32_t elapsed = now - clearSince_;
    return elapsed >= 3000 ? 0 : 3000 - elapsed;
  }

 private:
  bool automatic_ = true, opened_ = false, waiting_ = false, ready_ = false;
  uint32_t clearSince_ = 0, revision_ = 0;
};

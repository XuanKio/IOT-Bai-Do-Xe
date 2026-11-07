#pragma once
#include <stdint.h>

// Keep a digital input stable for the debounce period before reporting it.
// Unsigned subtraction also handles millis() rollover.
class GateSensor {
 public:
  void begin(uint8_t level, uint32_t now) {
    candidate_ = stable_ = level;
    changedAt_ = now;
    ready_ = false;
  }

  bool sample(uint8_t level, uint32_t now) {
    if (level != candidate_) {
      candidate_ = level;
      changedAt_ = now;
    }
    if (static_cast<uint32_t>(now - changedAt_) < 50) return false;
    if (ready_ && stable_ == candidate_) return false;
    stable_ = candidate_;
    ready_ = true;
    return true;
  }

  bool ready() const { return ready_; }
  uint8_t level() const { return stable_; }

 private:
  uint8_t candidate_ = 1;
  uint8_t stable_ = 1;
  uint32_t changedAt_ = 0;
  bool ready_ = false;
};

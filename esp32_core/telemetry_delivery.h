#pragma once
#include <stdint.h>

// Track application delivery, rather than only writes into a TCP send buffer.
class TelemetryDelivery {
 public:
  void reset(uint32_t now) {
    lastAckAt_ = now;
    sent_ = acknowledged_ = false;
  }
  void sent(uint32_t sequence) { highestSent_ = sequence; sent_ = true; }
  bool acknowledge(uint32_t sequence, uint32_t now) {
    if (!sent_ || sequence > highestSent_ || (acknowledged_ && sequence <= lastAckSequence_)) return false;
    lastAckAt_ = now;
    lastAckSequence_ = sequence;
    acknowledged_ = true;
    return true;
  }
  uint32_t age(uint32_t now) const { return now - lastAckAt_; }
  bool overdue(uint32_t now, uint32_t intervalMs) const {
    const uint32_t deadline = intervalMs * 3 + 2000;
    return sent_ && age(now) >= (deadline > 5000 ? deadline : 5000);
  }

 private:
  uint32_t highestSent_ = 0, lastAckSequence_ = 0, lastAckAt_ = 0;
  bool sent_ = false, acknowledged_ = false;
};

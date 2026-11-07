#include <assert.h>
#include "../../esp32_core/telemetry_delivery.h"

int main() {
  TelemetryDelivery delivery;
  delivery.reset(0);
  assert(!delivery.overdue(6000, 1000));  // No sample has been sent yet.
  delivery.sent(0);
  assert(!delivery.acknowledge(1, 10));  // Cannot acknowledge an unsent sample.
  assert(delivery.acknowledge(0, 10));
  assert(!delivery.acknowledge(0, 4000));  // A replay cannot keep the link alive.
  assert(!delivery.overdue(5009, 1000));
  assert(delivery.overdue(5010, 1000));
  delivery.sent(1);
  assert(delivery.acknowledge(1, 5010));
  assert(!delivery.overdue(5011, 1000));
  assert(!delivery.overdue(35009, 10000));
  assert(delivery.overdue(37010, 10000));
  delivery.reset(UINT32_MAX - 1000);
  delivery.sent(3);
  assert(!delivery.overdue(3998, 1000));
  assert(delivery.overdue(3999, 1000));
}

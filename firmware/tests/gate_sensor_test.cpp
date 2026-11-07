#include <assert.h>
#include "../../esp32_core/gate_sensor.h"

int main() {
  GateSensor entrance, exit;
  entrance.begin(1, 0);
  exit.begin(0, 0);
  assert(!entrance.ready());
  assert(!entrance.sample(1, 49));
  assert(entrance.sample(1, 50));
  assert(entrance.ready() && entrance.level() == 1);
  assert(exit.sample(0, 50) && exit.level() == 0);

  // A short LOW pulse and chatter cannot change a stable HIGH reading.
  assert(!entrance.sample(0, 60));
  assert(!entrance.sample(1, 80));
  assert(!entrance.sample(0, 100));
  assert(!entrance.sample(0, 149));
  assert(entrance.sample(0, 150) && entrance.level() == 0);
  assert(!entrance.sample(0, 160));
  assert(exit.level() == 0);
  assert(!entrance.sample(1, 200));
  assert(entrance.sample(1, 250) && entrance.level() == 1);

  GateSensor rollover;
  rollover.begin(1, UINT32_MAX - 20);
  assert(!rollover.sample(1, 10));
  assert(rollover.sample(1, 29));
  assert(rollover.ready() && rollover.level() == 1);
}

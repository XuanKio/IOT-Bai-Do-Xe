#include <assert.h>
#include "../../esp32_core/gate_controller.h"

int main() {
  GateController entry, exit;
  assert(entry.update(false, 0) && !entry.opened());
  exit.update(false, 0);
  assert(entry.update(true, 10) && entry.opened());
  assert(!exit.opened());
  entry.update(false, 100);
  assert(entry.remaining(100) == 3000);
  entry.update(false, 3099);
  assert(entry.opened());
  entry.update(false, 3100);
  assert(!entry.opened());

  entry.update(true, 4000);
  entry.update(false, 4100);
  entry.update(true, 7000);  // A returning car cancels the countdown.
  assert(entry.opened() && entry.remaining(7100) == 0);
  entry.update(false, 7200);
  entry.update(false, 10199);
  assert(entry.opened());
  entry.update(false, 10200);
  assert(!entry.opened());

  assert(!entry.setTarget(true, 1));  // Manual actions require manual mode.
  assert(entry.setMode(false, 1, false, 11000));
  assert(entry.setTarget(true, 2));
  entry.update(false, 50000);
  assert(entry.opened());  // Manual OPEN has no automatic close timer.
  assert(!entry.setTarget(false, 1));
  assert(entry.setTarget(false, 3));
  entry.update(true, 51000);
  assert(!entry.opened());  // Manual CLOSED ignores the presence sensor.
  assert(entry.setMode(true, 4, true, 52000) && entry.opened());
  assert(!entry.setMode(false, 4, false, 52001));

  GateController rollover;
  rollover.update(true, UINT32_MAX - 2000);
  rollover.update(false, UINT32_MAX - 1000);
  rollover.update(false, 1998);
  assert(rollover.opened());
  rollover.update(false, 1999);
  assert(!rollover.opened());

  GateController manualBoot;
  manualBoot.restoreMode(false);
  assert(manualBoot.update(true, 0));
  assert(!manualBoot.automatic() && !manualBoot.opened());
}

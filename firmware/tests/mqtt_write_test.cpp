#include <assert.h>
#include <string.h>
#include "../../esp32_core/mqtt_write.h"

int main() {
  const uint8_t packet[] = {1, 2, 3, 4, 5};
  uint8_t received[5] = {};
  uint32_t now = 0;
  size_t offset = 0;
  auto clock = [&]() -> uint32_t { return now; };
  auto pause = [&]() { now += 10; };
  auto chunks = [&](const uint8_t* data, size_t remaining) -> int {
    const size_t count = remaining > 2 ? 2 : remaining;
    memcpy(received + offset, data, count);
    offset += count;
    return static_cast<int>(count);
  };
  assert(boundedMqttWrite(packet, 5, 50, chunks, clock, pause) == 5);
  assert(memcmp(packet, received, 5) == 0);

  auto blocked = [](const uint8_t*, size_t) -> int { return 0; };
  assert(boundedMqttWrite(packet, 5, 50, blocked, clock, pause) == 0);
  assert(now == 50);

  int calls = 0;
  auto broken = [&](const uint8_t*, size_t) -> int { return ++calls == 1 ? 2 : -1; };
  assert(boundedMqttWrite(packet, 5, 50, broken, clock, pause) == 2);
  assert(calls == 2);  // A fatal failure cannot silently retry forever.

  now = UINT32_MAX - 20;
  assert(boundedMqttWrite(packet, 5, 50, blocked, clock, pause) == 0);
  assert(now == 29);
}

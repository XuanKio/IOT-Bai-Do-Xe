#pragma once
#include <stddef.h>
#include <stdint.h>

// writeChunk: positive bytes written, zero = retry, negative = fatal error.
// A single total deadline bounds repeated partial writes and full send buffers.
template <typename WriteChunk, typename Clock, typename Pause>
size_t boundedMqttWrite(const uint8_t* data, size_t size, uint32_t timeoutMs,
                        WriteChunk writeChunk, Clock clock, Pause pause) {
  const uint32_t started = clock();
  size_t total = 0;
  while (total < size && static_cast<uint32_t>(clock() - started) < timeoutMs) {
    const int result = writeChunk(data + total, size - total);
    if (result < 0 || static_cast<size_t>(result) > size - total) break;
    if (result > 0) total += static_cast<size_t>(result);
    else pause();
  }
  return total;
}

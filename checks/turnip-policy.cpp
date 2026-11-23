// SPDX-License-Identifier: MIT
#include "NativeTurnipPolicy.h"
#include <cassert>
#include <cstring>

int main(int argc, char **argv) {
    assert(argc == 3);
    unsetenv("TU_DEBUG");
    houji_turnip::configure();
    assert(std::strcmp(getenv("TU_DEBUG"), argv[1]) == 0);
    assert(std::strcmp(houji_turnip::renderMode(), argv[2]) == 0);
    houji_turnip::configure(); // Both discovery routes can call it.
    assert(std::strcmp(getenv("TU_DEBUG"), argv[1]) == 0);
    setenv("TU_DEBUG", "explicit-process-override", 1);
    houji_turnip::configure();
    assert(std::strcmp(getenv("TU_DEBUG"), "explicit-process-override") == 0);
}

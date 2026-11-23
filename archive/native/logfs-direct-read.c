// SPDX-License-Identifier: BSD-2-Clause-Patent
// Read-only Android helper: bypass block-page cache on this exact logfs device.
#define _GNU_SOURCE
#include <fcntl.h>
#include <linux/fs.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

int main(void) {
    char path[4096];
    if (!realpath("/dev/block/by-name/logfs", path) || strcmp(path, "/dev/block/sda13")) return 2;
    int fd = open(path, O_RDONLY | O_DIRECT | O_CLOEXEC);
    struct stat st;
    uint64_t size = 0;
    int sector = 0;
    if (fd < 0 || fstat(fd, &st) || !S_ISBLK(st.st_mode) ||
        ioctl(fd, BLKGETSIZE64, &size) || size != 8388608 ||
        ioctl(fd, BLKSSZGET, &sector) || sector != 4096) return 3;
    void *buffer = NULL;
    if (posix_memalign(&buffer, 4096, 4096)) return 4;
    for (unsigned block = 0; block < 2048; block++) {
        if (pread(fd, buffer, 4096, (off_t)block * 4096) != 4096) return 5;
        size_t done = 0;
        while (done < 4096) {
            ssize_t n = write(STDOUT_FILENO, (char *)buffer + done, 4096 - done);
            if (n <= 0) return 6;
            done += (size_t)n;
        }
    }
    free(buffer);
    return close(fd) ? 7 : 0;
}

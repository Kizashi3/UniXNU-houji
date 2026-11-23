# r213: Home search keyboard follow-up

The owner resumed installation and hardware testing on 2026-10-30. The intended
acceptance is a complete right keyboard edge in Home pull-down Spotlight search,
with the already accepted Settings search keyboard continuing to work.

The fresh 32 GiB pre-r213 snapshot matched the post-r212 root exactly across all
256 chunks, with no changes during capture. SHA-256:
`c5be3bdf2720de8d3aa81199bbc3811f688b922200cbee96d66c312563603878`.

The candidate installs the offline Spotlight v17 library using its absolute
application path. Preferences v16 remains hash-verified. The Spotlight library
SHA-256 is `2d79fbf242756d664e9ea2df75f48dcdf24dbabb305c6e1cdca40764a6017884`.

## Local shared-inode check

Local staging found that Spotlight's original `_CodeSignature/CodeResources`
inode had 234 hard links, including Preferences. The unchanged-runtime check
rejected that candidate before any phone userdata write. It is retained under
`native-port/ios-userland/native-keyboard-v17-shared-inode-check` and must never
be installed.

The corrected stager separates the Spotlight resource-envelope name before
writing it, while preserving the existing executable inode. The new library and
separated envelope receive root:80 ownership in the local candidate. An
owners-enabled read-only remount verified all three files, strict signatures,
unchanged app resources, and unchanged Preferences/GPU/helper hashes.

The verified candidate root SHA-256 is
`bdb6eebe21a4dee1cb1c39c6b538ccb095d3fa29a9c8dc7c410698f3606f3b11`.
Changed 128 MiB chunks: 0, 1, 90, 91. Delta manifest SHA-256:
`96b1b5676aea55be0cb06228cf2afd8448cc273819f484b0bb7351855a6954e9`.

## Runtime observation

Fresh log identity: `fb0c3ce1fe9a45149cf055d1147622ed`. The bounded terminal
collector reads the Preferences v16 and Spotlight v17 geometry log files after
the existing actual GPU isolation boundary. The files can contain earlier boots;
current-process load and method-call records must be distinguished from history.
No typed text is collected.

Installation completed with all 256 phone chunks matching the candidate.
Protected boot partitions, all GPT ranges and misc were unchanged. Fastboot
accepted the temporary image at 2026-10-30 18:50:26 +08:00; SHA-256
`5404223bf30b1caa1f27767ef459efa5381687387359345df65244fcf2e09de3`.
The background recovery listener started immediately after Booting OKAY.

The build freeze verified 427 files. Relative to r212, the UFS runtime changes
are the two keyboard-collector includes and the two fresh log identity headers.
Boot arguments, native device tree and the CPU/GPU/display execution profiles
are identical to r212. Owner acceptance and current-run keyboard log evidence
remain pending; neither install readback nor Fastboot acceptance proves UI
keyboard correction.

The owner subsequently confirmed both Home pull-down search and Settings search
are complete and usable. App Library search remained clipped. The CRC-valid
committed r213 log independently contains Spotlight v17 changing 375×233 to
400×233, and the matching current-process constructor/install records. Settings
v16 also reports its retained correction. Protected boot/GPT/misc checks passed.

The post-r213 immutable snapshot SHA-256 is
`2a1948861436cc0eccba2e96c44a89b7d487d5afe708d3022a5ad5cea28ec89f`.
It was captured on recovery ADB port 5038 after the device moved from 15049.
The first snapshot attempt failed at identity lookup before creating an output
or requesting userdata writes. The retry verified 20 changed chunks and stable
full readback. The owner requested unified keyboard handling and further
performance/120 Hz work; the follow-up is documented in
`unified-keyboard-refresh-r214.md`.

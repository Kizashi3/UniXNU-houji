"""Attach bounded terminal queries to the pinned CDC and UFS owners."""
from ios16_sources import kernel_source
from pathlib import Path
import json
import re


def debug_trust_source(manifest):
    data=json.loads(Path(manifest).read_text())
    if data.get('schema')!=1 or data.get('purpose')!='giulia-debug-userland':
        raise ValueError('Expected stage-debug-userland manifest')
    files=data.get('files',{})
    if not {'/usr/local/giulia/giulia-debugd','/usr/local/giulia/bin/sh'} <= files.keys():
        raise ValueError('Debug manifest lacks daemon or shell')
    hashes=set()
    for name, record in files.items():
        if not re.fullmatch(r'/usr/local/giulia/(?:giulia-debugd|(?:bin|lib)/[A-Za-z0-9_.+-]+)',name):
            raise ValueError('Debug trust path outside staged bundle')
        if not re.fullmatch('[0-9a-f]{64}',record.get('sha256','')):
            raise ValueError('Missing binary digest')
        values=record.get('cdhashes',[])
        if not values or any(not re.fullmatch('[0-9a-f]{40}',h) for h in values):
            raise ValueError('Invalid CodeDirectory hash')
        hashes.update(values)
    if not 1<=len(hashes)<=256:raise ValueError('Debug trust list exceeds 256 hashes')
    rows=',\n'.join('{'+','.join('0x'+h[i:i+2] for i in range(0,40,2))+'}' for h in sorted(hashes))
    return ('#include <pexpert/pexpert.h>\n'
            'static bool giulia_debug_trusted(const void *hash, size_t length) {\n'
            '    int enabled=0; PE_parse_boot_argn("giulia_debug",&enabled,sizeof(enabled));\n'
            '    if(enabled!=1 || !hash || length!=20) return false;\n'
            '    static const unsigned char hashes[][20]={'+rows+'};\n'
            '    for(unsigned i=0;i<sizeof(hashes)/sizeof(hashes[0]);i++)\n'
            '        if(!memcmp(hash,hashes[i],20)) return true;\n'
            '    return false;\n}\n')


def gpu_terminal_source(gpu=False):
    if gpu:
        return '#define GIULIA_GPU_INCLUDED 1\nextern int giulia_gpu_terminal(const char *);\n'
    return ('#define GIULIA_GPU_INCLUDED 0\n'
            'static int giulia_gpu_terminal(const char *command) {\n'
            '    if(strcmp(command,"gpu.status") && strcmp(command,"gpu.observe"))return 0;\n'
            '    printf("GIULIA GPU: command=%s service=unavailable stage=not-compiled hardware_ready=0 acceleration=0\\n",command);\n'
            '    return 1;\n}\n')


def keys_terminal_source(gui=False):
    if gui:
        return ('#define GIULIA_KEYS_INCLUDED 1\nextern void giulia_keys_debug(void);\n'
                'extern int giulia_slider_terminal(const char *);\n')
    return ('#define GIULIA_KEYS_INCLUDED 0\n'
            'static void giulia_keys_debug(void) {\n'
            '    printf("GIULIA KEYS: compiled=0 service=unavailable stage=not-compiled\\n");\n}\n'
            'static int giulia_slider_terminal(const char *cmd) {\n'
            '    if(strncmp(cmd,"slider.",7))return 0;\n'
            '    printf("GIULIA SLIDER: compiled=0 service=unavailable\\n");return 1;\n}\n')


def audio_terminal_source(audio=False):
    """Embed board metadata queries without acquiring audio hardware resources."""
    root = Path(__file__).resolve().parents[1]
    mapping = kernel_source((root/'ios16/audio/giulia_audio_mapping.h').read_text()).replace(
        '#include <stdint.h>\n', '').replace('#include <stddef.h>\n', '')
    runtime = ('extern int giulia_audio_runtime_command(const char *);\n' if audio else
               'static int giulia_audio_runtime_command(const char *cmd) {(void)cmd;return 0;}\n')
    return runtime + mapping + '\n' + kernel_source((root/'ios16/audio/giulia_audio_terminal.inc').read_text())


def terminal_sources(usb: Path, block: Path, edit, wifi=False, gui=False, gpu=False, audio=False, modem=False):
    if 'giulia_terminal_command' in usb.read_text():
        raise ValueError('Terminal integration already applied')
    root = Path(__file__).resolve().parents[1]
    abi = kernel_source((root/'ios16/common/giulia_debug_abi.h').read_text()).replace('#include <stdint.h>\n', '')
    shell = kernel_source((root/'ios16/terminal/giulia_shell.inc').read_text()).replace(
        '/* GIULIA_DEBUG_ABI is embedded here by the profile generator. */', abi)
    reboot = kernel_source((root/'ios16/platform/giulia_reboot.inc').read_text()).replace(
        '/* GIULIA_REBOOT_CORE is embedded here by the profile generator. */',
        kernel_source((root/'ios16/platform/giulia_reboot.h').read_text()).replace('#include <stdint.h>\n', ''))
    screen = kernel_source((root/'ios16/terminal/giulia_screen.inc').read_text()).replace(
        '/* GIULIA_SCREEN_CORE is embedded here by the profile generator. */',
        kernel_source((root/'ios16/terminal/giulia_screen.h').read_text()).replace('#include <stdint.h>\n','').replace('#include <stddef.h>\n',''))
    screen = screen.replace('/* GIULIA_SCREEN_PROVIDER is embedded here by the profile generator. */',
        'extern int giulia_screen_capture_size(uint8_t *,size_t,unsigned *,unsigned *,unsigned);' if gui else
        'static int giulia_screen_capture_size(uint8_t *p,size_t n,unsigned *w,unsigned *h,unsigned m) '
        '{(void)p;(void)n;(void)w;(void)h;(void)m;return 0;}')
    remote = kernel_source((root/'ios16/terminal/giulia_input.inc').read_text()).replace(
        '/* GIULIA_INPUT_PROVIDER is embedded here by the profile generator. */',
        ('extern unsigned giulia_remote_ready(void);\n'
         'extern int giulia_remote_touch(unsigned,unsigned,unsigned);\n'
         'extern int giulia_remote_hid(unsigned,unsigned,unsigned);') if gui else
        ('static unsigned giulia_remote_ready(void) {return 0;}\n'
         'static int giulia_remote_touch(unsigned d,unsigned x,unsigned y) {(void)d;(void)x;(void)y;return 0;}\n'
         'static int giulia_remote_hid(unsigned p,unsigned u,unsigned d) {(void)p;(void)u;(void)d;return 0;}'))
    screen = screen.replace('/* GIULIA_INPUT_CORE is embedded here by the profile generator. */', remote)
    code = (keys_terminal_source(gui) + gpu_terminal_source(gpu) + 'extern unsigned long gPhysBase, gPhysSize;\n' + shell + '\n' +
            kernel_source((root/'ios16/terminal/giulia_mmio.inc').read_text()) + '\n' +
            reboot + '\n' + screen + '\n' + audio_terminal_source(audio) + '\n' +
            kernel_source((root / 'ios16/terminal/giulia_terminal.inc').read_text()))
    if audio:
        code = code.replace('audio=audio.status,audio.map stage=board-mapping-only hardware_ready=0 playback=0 recording=0',
                            'audio=audio.status,audio.map,audio.preflight,audio.start,audio.stop,audio.test runtime=1 provider_required=1 hardware_verified=0')
    if modem:
        code='extern int giulia_modem_terminal(const char *);\n'+code
        code=code.replace('    if(gaudio_command(cmd))return 1;',
                          '    if(giulia_modem_terminal(cmd))return 1;\n    if(gaudio_command(cmd))return 1;')
        anchor='        printf("GIULIA TERM: keys=keys.status compiled='
        if code.count(anchor)!=1:raise ValueError('Terminal feature anchor changed')
        code=code.replace(anchor,
                          '        printf("GIULIA TERM: modem=modem.status,modem.start,modem.stop,modem.suspend,modem.resume runtime_abi=1\\n");\n'+anchor)
    if wifi:
        code='extern int giulia_wifi_terminal(const char *);\n'+code
        code=code.replace('    if(gs_command(cmd) || gm_command(cmd) || gr_command(cmd)) return 1;',
                          '    if(giulia_wifi_terminal(cmd) || gs_command(cmd) || gm_command(cmd) || gr_command(cmd)) return 1;')
    edit(usb, 'static void command_line(void)', code + '\nstatic void command_line(void)')
    # Keep ping/sample/status adjacent: the complete-boot-log patch uses them
    # as context when it extends the status response later in the GUI profile.
    edit(usb, '    else if (!strcmp(u.command,"ping"))',
         '    else if (giulia_terminal_command(u.command)) {}\n'
         '    else if (!strcmp(u.command,"ping"))')
    edit(usb, 'commands help status ping replay',
         'commands help status ping replay info uptime memory ps bootargs display usb ufs features shell shell.size reg.* reboot.fastboot reboot.status screen.start screen.stop screen.snapshot screen.configure input.status input.touch input.key input.button input.release input.keepalive gpu.status gpu.observe audio.status audio.map'
         + ' keys.status slider.status slider.calibrate slider.hid slider.stop'
         + (' audio.preflight audio.start audio.stop audio.test' if audio else ''))
    if modem:
        edit(usb, 'audio.status audio.map',
             'audio.status audio.map modem.status modem.start modem.stop modem.suspend modem.resume')
    edit(usb, '; queries only', '; shell/MMIO require development boot args')
    edit(usb, '(read only)', '(development protocol 2)')
    edit(usb, 'RAM log and read-only commands', 'RAM log and protocol 2 terminal')
    edit(usb, 'USB can read the RAM console ring and issue four bounded queries only.',
         'USB exposes log queries plus opt-in root PTY and explicit MMIO access.')
    edit(usb, '    sync_dma(RX,RX_SIZE);u.rx_bytes+=length;',
         '    sync_dma(RX,RX_SIZE);u.rx_bytes+=length;\n'
         '    if (gs_receive((const uint8_t *)(u.dma+RX),length)) { receive_arm(); return; }')
    edit(usb, '    unsigned n=vermeer_debug_copy(&u.cursor,(char *)(u.dma+TX),TX_SIZE);',
         '    unsigned screen_n=0;\n'
         '    if (gscreen_transmit((uint8_t *)(u.dma+TX),TX_SIZE-1,&screen_n)) {\n'
         '        if(screen_n) { transfer(3,TX,screen_n,T_NORMAL);u.tx_bytes+=screen_n; }\n'
         '        return;\n    }\n'
         '    unsigned shell_n=0;\n'
         '    if (gs_transmit((char *)(u.dma+TX),u.mps-1,&shell_n)) {\n'
         '        if(shell_n) { transfer(3,TX,shell_n,T_NORMAL);u.tx_bytes+=shell_n; }\n'
         '        return;\n    }\n'
         '    unsigned n=vermeer_debug_copy(&u.cursor,(char *)(u.dma+TX),TX_SIZE);')
    edit(usb, '    while (!u.failed) {', '    gs_register();\n    while (!u.failed) {')
    edit(usb, '        transmit();',
         '        ginput_tick(gscreen_now());\n'
         '        if (!u.configured || !u.dtr) {gs_disconnect();gscreen_disconnect();}\n        transmit();')
    edit(usb, '    wr(DEVTEN,0);wr(DCTL,rd(DCTL)&~RUN);\n    thread_terminate(current_thread());',
         '    gs_disconnect();gscreen_disconnect();\n    wr(DEVTEN,0);wr(DCTL,rd(DCTL)&~RUN);\n    thread_terminate(current_thread());')
    code = kernel_source((root / 'ios16/storage/giulia_terminal_ufs.inc').read_text())
    edit(block, 'static uint64_t vb_device_bytes(void)', code + '\nstatic uint64_t vb_device_bytes(void)')

/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Ace 5 AK09970 preparation policy. Native providers own power/clock writes.
 * No pin, reset, PMIC address, or sensor-register programming belongs here.
 */
#ifndef GIULIA_HALL_PREPARE_POLICY_H
#define GIULIA_HALL_PREPARE_POLICY_H
#ifdef GHP_FIRMWARE_TYPES
typedef UINT32 GHP_U32;
typedef UINT64 GHP_U64;
#else
#include <stdint.h>
typedef uint32_t GHP_U32;
typedef uint64_t GHP_U64;
#endif

enum { GHP_OK, GHP_ARGUMENT, GHP_RESOLVE, GHP_ADDRESS, GHP_CREATE,
       GHP_ISSUE, GHP_WAIT, GHP_RATE, GHP_ENABLE, GHP_OFF };
struct ghp_result {
    GHP_U32 stage, address, attempted, ready, code;
    GHP_U64 status;
};
struct ghp_power_io {
    void *context;
    GHP_U64 (*resolve)(void *,GHP_U32 *,GHP_U32 *);
    GHP_U64 (*create)(void *);
    GHP_U64 (*issue)(void *,GHP_U32,GHP_U32,GHP_U32 *);
    GHP_U64 (*wait)(void *,GHP_U32);
};
struct ghp_clock_io {
    void *context;
    GHP_U64 (*resolve)(void *);
    GHP_U64 (*rate)(void *,GHP_U32,GHP_U32 *);
    GHP_U64 (*get_rate)(void *,GHP_U32 *);
    GHP_U64 (*enable)(void *,unsigned);
    GHP_U64 (*on)(void *,unsigned,GHP_U32 *);
};
static inline unsigned ghp_fail(struct ghp_result *r,unsigned code,GHP_U64 status)
{
    r->code=code;r->status=status;return code;
}
static inline unsigned ghp_power_prepare(const struct ghp_power_io *io,struct ghp_result *r)
{
    GHP_U32 slave=0,request=0;
    GHP_U64 status;
    static const GHP_U32 offsets[3]={0,8,4};
    static const GHP_U32 values[3]={1800,7,1};
    if(!io || !r || !io->resolve || !io->create || !io->issue || !io->wait)return GHP_ARGUMENT;
    *r=(struct ghp_result){0};r->stage=1;
    status=io->resolve(io->context,&r->address,&slave);
    if(status)return ghp_fail(r,GHP_RESOLVE,status);
    r->stage=4;
    /* CmdDb slave 4 is VRM, not an SPMI SID. A resource has a 16-byte bank. */
    if(slave!=4 || (r->address>>16)!=4 || (r->address&15))return ghp_fail(r,GHP_ADDRESS,0);
    r->stage=6;status=io->create(io->context);
    if(status)return ghp_fail(r,GHP_CREATE,status);
    for(unsigned i=0;i<3;i++) {
        r->stage=7+i;r->attempted=1;request=0;
        status=io->issue(io->context,r->address+offsets[i],values[i],&request);
        if(status)return ghp_fail(r,GHP_ISSUE,status);
        if(request) {
            status=io->wait(io->context,request);
            if(status)return ghp_fail(r,GHP_WAIT,status);
        }
    }
    r->stage=10;r->ready=1;return GHP_OK;
}
static inline unsigned ghp_clock_prepare(const struct ghp_clock_io *io,struct ghp_result *r)
{
    GHP_U64 status;
    GHP_U32 actual=0,on=0;
    if(!io || !r || !io->resolve || !io->rate || !io->get_rate || !io->enable || !io->on)return GHP_ARGUMENT;
    *r=(struct ghp_result){0};r->stage=1;
    status=io->resolve(io->context);
    if(status)return ghp_fail(r,GHP_RESOLVE,status);
    r->stage=2;r->attempted=1;
    status=io->rate(io->context,19200000,&actual);
    if(status || actual!=19200000)return ghp_fail(r,GHP_RATE,status);
    r->stage=3;actual=0;status=io->get_rate(io->context,&actual);
    if(status || actual!=19200000)return ghp_fail(r,GHP_RATE,status);
    for(unsigned i=0;i<3;i++) {
        r->stage=4+i;r->address=i;
        status=io->enable(io->context,i);
        if(status)return ghp_fail(r,GHP_ENABLE,status);
    }
    /* Native hub core first, then wrapper AHB and SE8, as stock runtime
     * resume requests them. An AHB branch can be idle/HW gated before its
     * dependencies exist: observe only after every enable request. Keep
     * the on check strict; a completed vote alone is not ready. */
    for(unsigned i=0;i<3;i++) {
        r->stage=7+i;r->address=i;
        on=0;status=io->on(io->context,i,&on);
        if(status || on!=1)return ghp_fail(r,GHP_OFF,status);
    }
    r->stage=10;r->ready=1;return GHP_OK;
}
#endif

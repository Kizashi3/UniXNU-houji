/* Real existing CPU SHA implementation; no model digest. */
#include "NativeAdrenoSha256.h"
#include <stddef.h>
#include <stdint.h>
extern "C" int fhg_real_sha(void *,const uint8_t *p,size_t n,uint8_t out[32]) {
 NativeAdrenoSha256::hash(p,n,out);return 0;
}

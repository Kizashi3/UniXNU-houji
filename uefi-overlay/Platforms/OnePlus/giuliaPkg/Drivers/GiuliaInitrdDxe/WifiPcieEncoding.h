/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Fixed 168-byte little-endian AArch64 report -> 224 base64 characters.
 * Keeps the complete report within Darwin22's 608-byte command line.
 * Include WifiPcieReport.h first. The consumer checks the embedded version.
 */
#ifndef GIULIA_WIFI_PCIE_ENCODING_H
#define GIULIA_WIFI_PCIE_ENCODING_H
static int gw_report_base64(char *out,unsigned capacity,const struct gw_report *r)
{
  static const char alphabet[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  const unsigned char *bytes=(const unsigned char *)r;
  unsigned i,j=0;
  if(!out || !r || sizeof(*r)!=168 || capacity<225) return 0;
  for(i=0;i<168;i+=3) {
    unsigned n=168-i,value=(unsigned)bytes[i]<<16;
    if(n>1) value|=(unsigned)bytes[i+1]<<8;
    if(n>2) value|=bytes[i+2];
    out[j++]=alphabet[(value>>18)&63]; out[j++]=alphabet[(value>>12)&63];
    out[j++]=n>1?alphabet[(value>>6)&63]:'=';
    out[j++]=n>2?alphabet[value&63]:'=';
  }
  out[j]=0;
  return 1;
}
#endif

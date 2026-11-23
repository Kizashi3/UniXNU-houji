#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#define SWEET_SURFACE_RESULT_SIZE 2048
#define SWEET_SURFACE_TIMESTAMPS 256
struct Addr {uint64_t getAddress(){return 0x100000000ull;}};
struct sweet_surface_plane {uint32_t width,height,bytesPerRow,offset,size;uint16_t bytesPerElement;uint8_t elementWidth,elementHeight;};
struct SweetSurface {uint32_t id,width,height,bytesPerRow,offset,pixelFormat,allocSize,planeCount,cacheMode,parentID;uint16_t bytesPerElement;uint8_t elementWidth,elementHeight;sweet_surface_plane planes[4];Addr*state;};
struct SweetSurfaceRef {Addr*data;Addr*state;};
static void put32(uint8_t*p,uint32_t at,uint32_t v){memcpy(p+at,&v,4);}
static void put64(uint8_t*p,uint32_t at,uint64_t v){memcpy(p+at,&v,8);}
static uint32_t get32(uint8_t*p,uint32_t at){uint32_t v;memcpy(&v,p+at,4);return v;}
static void
sweet_surface_fill_result(SweetSurface *s, SweetSurfaceRef *ref, uint8_t *out)
{
	bzero(out, SWEET_SURFACE_RESULT_SIZE);
	put64(out, 0x00, ref->data->getAddress());
	put64(out, 0x08, ref->state->getAddress());
	put64(out, 0x10, ref->state->getAddress() + SWEET_SURFACE_TIMESTAMPS);
	put32(out, 0x18, s->id);
	put32(out, 0x1c, s->allocSize);
	put32(out, 0x20, s->width);
	put32(out, 0x24, s->height);
	put32(out, 0x28, s->bytesPerRow);
	put32(out, 0x2c, s->offset);
	put32(out, 0x30, s->pixelFormat);
	put32(out, 0x34, s->allocSize);
	put32(out, 0x38, s->planeCount);
	memcpy(out + 0x40, &s->bytesPerElement, 2);
	out[0x42] = s->elementWidth;
	out[0x43] = s->elementHeight;
	put32(out, 0x44, s->cacheMode);
	put32(out, 0x50, s->parentID);
	put32(out, 0x54, 1);
	for (uint32_t i = 0; i < s->planeCount; i++) {
		uint8_t *p = out + 0x68 + i * 0x80;
		const struct sweet_surface_plane *pl = &s->planes[i];
		put32(p, 0x00, pl->width);
		put32(p, 0x04, pl->height);
		put32(p, 0x08, pl->bytesPerRow);
		put32(p, 0x0c, pl->offset);
		put32(p, 0x14, pl->size);
		memcpy(p + 0x18, &pl->bytesPerElement, 2);
		p[0x1a] = pl->elementWidth;
		p[0x1b] = pl->elementHeight;
	}
}
int main(){Addr a;SweetSurface s={};s.state=&a;SweetSurfaceRef r{&a,&a};uint8_t out[SWEET_SURFACE_RESULT_SIZE];unsigned n=0;for(unsigned count=0;count<=4;count++){s.planeCount=count;s.bytesPerRow=4864;for(unsigned i=0;i<count;i++){s.planes[i]={1200,2670,4864+i*128,i*0x100000,0x100000,4,1,1};}sweet_surface_fill_result(&s,&r,out);if(get32(out,0x28)!=4864||get32(out,0x38)!=count)return 1;for(unsigned i=0;i<count;i++){/* Independent reader: 20H392 client result copied at +0x68; actual row accessor loads +0xe0+i*0x80. */unsigned row_slot=0xe0-0x68+i*0x80;if(get32(out,row_slot)!=s.planes[i].bytesPerRow)return 2;if(get32(out,0xdc-0x68+i*0x80)!=s.planes[i].offset)return 3;if(get32(out,0xd0-0x68+i*0x80)!=1200)return 4;n++;}}printf("PASS actual serializer vs iOS16 binary reader: %u planar rows; ordinary geometry preserved\n",n);}

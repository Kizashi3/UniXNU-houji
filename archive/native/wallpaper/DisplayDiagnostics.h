// SPDX-License-Identifier: MIT
// Bounded, local diagnostics for the owner's Settings keyboard layout.
#import <UIKit/UIKit.h>
#import <IOSurface/IOSurfaceRef.h>
#import <ImageIO/ImageIO.h>
#import <sys/stat.h>
static void displayDiagnostics(unsigned sample) {
 @try {
  UIScreen *screen=UIScreen.mainScreen;
  CGRect b=screen.bounds,n=screen.nativeBounds;
  note(@"SCREEN %u bounds=%.3f,%.3f %.3fx%.3f scale=%.5f native=%.3fx%.3f nativeScale=%.5f",sample,b.origin.x,b.origin.y,b.size.width,b.size.height,screen.scale,n.size.width,n.size.height,screen.nativeScale);
 }@catch(NSException *e){note(@"SCREEN exception %@ %@",e.name,e.reason);}
 // Surface 1 is the physical display published by this board. It is read
 // only and never used as an input texture here. The CPU copy is not an
 // atomic capture of panel scanout; these PNGs diagnose stable geometry.
 IOSurfaceRef surface=IOSurfaceLookup(1);
 if(!surface){note(@"SCREEN %u physical surface unavailable",sample);return;}
 size_t w=IOSurfaceGetWidth(surface),h=IOSurfaceGetHeight(surface),row=IOSurfaceGetBytesPerRow(surface),bytes=IOSurfaceGetAllocSize(surface);
 note(@"SCREEN %u surface=%zux%zu row=%zu allocation=%zu pixel-format=%08x",sample,w,h,row,bytes,IOSurfaceGetPixelFormat(surface));
 if(w!=1200 || h!=2670 || row!=4800 || bytes<row*h){CFRelease(surface);return;}
 // This continuously displayed surface is sampled without waiting for GPU
 // ownership. The image may cross a present; it only diagnoses geometry.
 note(@"SCREEN %u before no-sync read lock",sample);
 uint32_t seed=0;IOSurfaceLockOptions options=kIOSurfaceLockReadOnly|kIOSurfaceLockAvoidSync;
 int locked=IOSurfaceLock(surface,options,&seed);
 note(@"SCREEN %u after no-sync read lock status=%x",sample,locked);
 if(locked){note(@"SCREEN %u lock=%x",sample,locked);CFRelease(surface);return;}
 note(@"SCREEN %u before base lookup",sample);
 const void *base=IOSurfaceGetBaseAddress(surface);
 note(@"SCREEN %u after base lookup mapped=%d",sample,base!=NULL);
 NSData *copy=base?[NSData dataWithBytes:base length:row*h]:nil;
 note(@"SCREEN %u CPU copy bytes=%lu",sample,(unsigned long)copy.length);
 IOSurfaceUnlock(surface,options,&seed);CFRelease(surface);
 if(!copy)return;
 CGDataProviderRef provider=CGDataProviderCreateWithCFData((__bridge CFDataRef)copy);
 CGColorSpaceRef colors=CGColorSpaceCreateDeviceRGB();
 // Scanout RGB is visible even when its unused alpha byte is zero.
 CGImageRef image=CGImageCreate(w,h,8,32,row,colors,kCGBitmapByteOrder32Little|kCGImageAlphaNoneSkipFirst,provider,NULL,false,kCGRenderingIntentDefault);
 note(@"SCREEN %u PNG encode begin image=%d",sample,image!=NULL);
 if(image){
  NSString *path=[NSString stringWithFormat:@"/private/var/mobile/Library/Logs/UniXNU-screen-%u.png",sample];
  CGImageDestinationRef dest=CGImageDestinationCreateWithURL((__bridge CFURLRef)[NSURL fileURLWithPath:path],CFSTR("public.png"),1,NULL);
  BOOL saved=NO;if(dest){CGImageDestinationAddImage(dest,image,NULL);saved=CGImageDestinationFinalize(dest);CFRelease(dest);}
  if(saved)chmod(path.fileSystemRepresentation,0600);
  note(@"SCREEN %u PNG saved=%d, CPU display copy for geometry; not atomic panel capture",sample,saved);
  CGImageRelease(image);
 }
 CGColorSpaceRelease(colors);CGDataProviderRelease(provider);
}

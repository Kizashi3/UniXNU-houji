// Read-only display metrics for the owner's iOS16 build. Never read scanout.
#import <UIKit/UIKit.h>
static void displayDiagnostics(unsigned sample) {
 @try {
  UIScreen *screen=UIScreen.mainScreen;
  CGRect b=screen.bounds,n=screen.nativeBounds;
  note(@"SCREEN %u bounds=%.3f,%.3f %.3fx%.3f scale=%.5f native=%.3fx%.3f nativeScale=%.5f",sample,b.origin.x,b.origin.y,b.size.width,b.size.height,screen.scale,n.size.width,n.size.height,screen.nativeScale);
  void *lib=dlopen("/usr/lib/libMobileGestalt.dylib",RTLD_NOW|RTLD_LOCAL);
  CFTypeRef (*answer)(CFStringRef)=lib?(CFTypeRef(*)(CFStringRef))dlsym(lib,"MGCopyAnswer"):NULL;
  if(!answer){note(@"GESTALT %u display query unavailable",sample);return;}
  for(NSString *key in @[@"MainScreenStaticInfo",@"MainScreenCanvasSizes",@"oBbtJ8x+s1q0OkaiocPuog",@"ybGkijAwLTwevankfVzsDQ"]){
   CFTypeRef value=answer((__bridge CFStringRef)key);
   double number=0;
   if(value && CFGetTypeID(value)==CFNumberGetTypeID() && CFNumberGetValue((CFNumberRef)value,kCFNumberDoubleType,&number))
    note(@"GESTALT %u %@=%.6f",sample,key,number);
   else if(value) {
    CFTypeID type=CFGetTypeID(value);
    NSString *description=[(__bridge id)value description];
    if(description.length>1800)description=[description substringToIndex:1800];
    note(@"GESTALT %u %@ type=%lu value=%@",sample,key,(unsigned long)type,description);
   } else note(@"GESTALT %u %@ unavailable",sample,key);
   if(value)CFRelease(value);
  }
  // Keep the library resident; this runs only three bounded samples.
 }@catch(NSException *e){note(@"SCREEN exception %@ %@",e.name,e.reason);}
}

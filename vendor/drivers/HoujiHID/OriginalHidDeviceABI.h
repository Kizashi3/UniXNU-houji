#pragma once

#include <IOKit/IOService.h>
#include <IOKit/IOMemoryDescriptor.h>

// The original 20H392 IOHIDFamily supplies these methods and this metaclass.
class IOHIDDevice : public IOService {
    OSDeclareAbstractStructors(IOHIDDevice)
    unsigned char devicePrivate[0xd0 - sizeof(IOService)];

public:
    using IOService::setProperty;
    IOReturn Dispatch(IORPC) override;
    void free() override;
    bool init(OSDictionary *properties = nullptr) override;
    bool setProperty(const OSSymbol *, OSObject *) override;
    bool willTerminate(IOService *, IOOptionBits) override;
    IOReturn configureReport(IOReportChannelList *, IOReportConfigureAction, void *, void *) override;
    IOReturn updateReport(IOReportChannelList *, IOReportUpdateAction, void *, void *) override;
    bool start(IOService *) override;
    void stop(IOService *) override;
    bool handleOpen(IOService *, IOOptionBits, void *) override;
    void handleClose(IOService *, IOOptionBits) override;
    bool handleIsOpen(const IOService *) const override;
    bool matchPropertyTable(OSDictionary *, SInt32 *) override;
    IOReturn message(UInt32, IOService *, void *) override;
    IOReturn newUserClient(task_t, void *, UInt32, OSDictionary *, IOUserClient **) override;

    // Opaque entries are inherited at their original slots and are never called here.
    virtual void opaque168();
    virtual void opaque169();
    virtual void opaque170();
    virtual OSString *newTransportString() const;
    virtual void opaque172();
    virtual OSString *newProductString() const;
    virtual void opaque174();
    virtual void opaque175();
    virtual void opaque176();
    virtual void opaque177();
    virtual void opaque178();
    virtual void opaque179();
    virtual IOReturn newReportDescriptor(IOMemoryDescriptor **) const = 0;
    virtual IOReturn handleReport(IOMemoryDescriptor *, unsigned, IOOptionBits);
    virtual void opaque182();
    virtual void opaque183();
    virtual void opaque184();
    virtual void opaque185();
    virtual void opaque186();
    virtual void opaque187();
    virtual void opaque188();
    virtual void opaque189();
    virtual void opaque190();
    virtual void opaque191();
    virtual void opaque192();
    virtual void opaque193();
    virtual void opaque194();
    virtual void opaque195();
    virtual void opaque196();
    virtual void opaque197();
    virtual void opaque198();
    virtual void opaque199();
    virtual void opaque200();
    virtual void opaque201();
    virtual void opaque202();
    virtual void opaque203();
    virtual void opaque204();
    virtual void opaque205();
    virtual void opaque206();
};
static_assert(sizeof(IOHIDDevice) == 0xd0);

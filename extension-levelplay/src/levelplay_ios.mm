#if defined(DM_PLATFORM_IOS)

#include "levelplay_callback_private.h"
#include "levelplay_private.h"

#include <dmsdk/sdk.h>

#include <cmath>
#include <string>

#import <UIKit/UIKit.h>
#import <dispatch/dispatch.h>
#import <objc/message.h>

// The LevelPlay Swift package continues to expose its native SDK through this
// vendor-owned module name.
#import "IronSource/IronSource.h"

#if __has_include(<AppTrackingTransparency/ATTrackingManager.h>)
#import <AppTrackingTransparency/ATTrackingManager.h>
#endif

@interface DMLevelPlayInterstitialDelegate : NSObject<LPMInterstitialAdDelegate>
{
    int m_Handle;
}
- (instancetype)initWithHandle:(int)handle;
@end

@interface DMLevelPlayRewardedDelegate : NSObject<LPMRewardedAdDelegate>
{
    int m_Handle;
}
- (instancetype)initWithHandle:(int)handle;
@end

@interface DMLevelPlayBannerDelegate : NSObject<LPMBannerAdViewDelegate>
{
    int m_Handle;
}
- (instancetype)initWithHandle:(int)handle;
@end

namespace dmLevelPlay
{

static NSMutableDictionary* s_InterstitialAds = nil;
static NSMutableDictionary* s_InterstitialDelegates = nil;
static NSMutableDictionary* s_RewardedAds = nil;
static NSMutableDictionary* s_RewardedDelegates = nil;
static NSMutableDictionary* s_BannerAds = nil;
static NSMutableDictionary* s_BannerDelegates = nil;
static NSMutableDictionary* s_BannerSizes = nil;
static NSMutableDictionary* s_BannerPositions = nil;
static NSMutableDictionary* s_BannerSafeAreas = nil;
static NSMutableDictionary* s_BannerConstraints = nil;

static int s_NextHandle = 1;
static bool s_Initialized = false;
static bool s_Initializing = false;
static bool s_Active = false;
static bool s_APSEnabled = false;
static bool s_APSConfigured = false;
static unsigned int s_LifetimeGeneration = 0;
static std::string s_APSAppId;
static std::string s_StringResult;

static const int ERROR_NOT_INITIALIZED = -1;
static const int ERROR_INVALID_ARGUMENT = -2;
static const int ERROR_INVALID_HANDLE = -3;
static const int ERROR_NO_VIEW_CONTROLLER = -4;
static const int ERROR_NETWORK_CONFIGURATION = -5;
static const int ERROR_SDK_EXCEPTION = -6;

static void RunOnMainSync(dispatch_block_t block)
{
    if ([NSThread isMainThread])
    {
        block();
    }
    else
    {
        dispatch_sync(dispatch_get_main_queue(), block);
    }
}

static void RunOnMainAsync(dispatch_block_t block)
{
    if ([NSThread isMainThread])
    {
        block();
    }
    else
    {
        dispatch_async(dispatch_get_main_queue(), block);
    }
}

static void EnsureStorage()
{
    if (s_InterstitialAds)
    {
        return;
    }

    s_InterstitialAds = [[NSMutableDictionary alloc] init];
    s_InterstitialDelegates = [[NSMutableDictionary alloc] init];
    s_RewardedAds = [[NSMutableDictionary alloc] init];
    s_RewardedDelegates = [[NSMutableDictionary alloc] init];
    s_BannerAds = [[NSMutableDictionary alloc] init];
    s_BannerDelegates = [[NSMutableDictionary alloc] init];
    s_BannerSizes = [[NSMutableDictionary alloc] init];
    s_BannerPositions = [[NSMutableDictionary alloc] init];
    s_BannerSafeAreas = [[NSMutableDictionary alloc] init];
    s_BannerConstraints = [[NSMutableDictionary alloc] init];
}

static NSNumber* HandleKey(int handle)
{
    return [NSNumber numberWithInt:handle];
}

static NSString* RequiredString(const char* value)
{
    if (!value || value[0] == '\0')
    {
        return nil;
    }
    return [NSString stringWithUTF8String:value];
}

static NSString* OptionalString(const char* value)
{
    return RequiredString(value);
}

static UIViewController* CurrentRootViewController()
{
    UIWindow* window = dmGraphics::GetNativeiOSUIWindow();
    return window ? window.rootViewController : nil;
}

static UIViewController* PresentationViewController()
{
    UIViewController* controller = CurrentRootViewController();
    while (controller)
    {
        if (controller.presentedViewController &&
            !controller.presentedViewController.isBeingDismissed)
        {
            controller = controller.presentedViewController;
        }
        else if ([controller isKindOfClass:[UINavigationController class]])
        {
            controller = [(UINavigationController*)controller visibleViewController];
        }
        else if ([controller isKindOfClass:[UITabBarController class]])
        {
            controller = [(UITabBarController*)controller selectedViewController];
        }
        else
        {
            break;
        }
    }
    return controller;
}

static int AllocateHandle()
{
    for (;;)
    {
        int handle = s_NextHandle++;
        if (s_NextHandle <= 0)
        {
            s_NextHandle = 1;
        }
        if (handle > 0 &&
            ![s_InterstitialAds objectForKey:HandleKey(handle)] &&
            ![s_RewardedAds objectForKey:HandleKey(handle)] &&
            ![s_BannerAds objectForKey:HandleKey(handle)])
        {
            return handle;
        }
    }
}

static void SetIfPresent(NSMutableDictionary* dictionary, NSString* key, id value)
{
    if (value)
    {
        [dictionary setObject:value forKey:key];
    }
}

static NSMutableDictionary* AdInfoDictionary(LPMAdInfo* adInfo)
{
    NSMutableDictionary* dictionary = [NSMutableDictionary dictionary];
    if (!adInfo)
    {
        return dictionary;
    }

    SetIfPresent(dictionary, @"ad_id", adInfo.adId);
    SetIfPresent(dictionary, @"ad_unit_id", adInfo.adUnitId);
    SetIfPresent(dictionary, @"ad_unit_name", adInfo.adUnitName);
    SetIfPresent(dictionary, @"placement_name", adInfo.placementName);
    SetIfPresent(dictionary, @"ad_format", adInfo.adFormat);
    SetIfPresent(dictionary, @"auction_id", adInfo.auctionId);
    SetIfPresent(dictionary, @"country", adInfo.country);
    SetIfPresent(dictionary, @"ab", adInfo.ab);
    SetIfPresent(dictionary, @"segment_name", adInfo.segmentName);
    SetIfPresent(dictionary, @"ad_network", adInfo.adNetwork);
    SetIfPresent(dictionary, @"instance_name", adInfo.instanceName);
    SetIfPresent(dictionary, @"instance_id", adInfo.instanceId);
    SetIfPresent(dictionary, @"revenue", adInfo.revenue);
    SetIfPresent(dictionary, @"precision", adInfo.precision);
    SetIfPresent(dictionary, @"encrypted_cpm", adInfo.encryptedCPM);
    SetIfPresent(dictionary, @"conversion_value", adInfo.conversionValue);
    SetIfPresent(dictionary, @"creative_id", adInfo.creativeId);

    LPMAdSize* adSize = adInfo.adSize;
    if (adSize)
    {
        SetIfPresent(dictionary, @"ad_size_description", adSize.sizeDescription);
        [dictionary setObject:[NSNumber numberWithInteger:adSize.width] forKey:@"ad_width"];
        [dictionary setObject:[NSNumber numberWithInteger:adSize.height] forKey:@"ad_height"];
        [dictionary setObject:[NSNumber numberWithBool:adSize.isAdaptive]
                       forKey:@"ad_size_is_adaptive"];
    }
    return dictionary;
}

static void AddError(NSMutableDictionary* dictionary, NSError* error)
{
    if (!error)
    {
        return;
    }
    [dictionary setObject:[NSNumber numberWithInteger:error.code] forKey:@"error_code"];
    SetIfPresent(dictionary, @"error_message", error.localizedDescription);
    SetIfPresent(dictionary, @"error_domain", error.domain);
}

static NSString* JSONString(NSDictionary* dictionary, NSError** outputError)
{
    NSData* data = [NSJSONSerialization dataWithJSONObject:dictionary
                                                   options:(NSJSONWritingOptions)0
                                                     error:outputError];
    if (!data)
    {
        return nil;
    }
    return [[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] autorelease];
}

static void SendDictionary(int message, int event, int handle, NSDictionary* dictionary)
{
    if (!s_Active)
    {
        return;
    }

    NSError* error = nil;
    NSString* json = JSONString(dictionary ? dictionary : [NSDictionary dictionary], &error);
    if (json)
    {
        AddToQueueCallback(message, event, handle, json.UTF8String);
        return;
    }

    NSDictionary* fallback = [NSDictionary dictionaryWithObjectsAndKeys:
        error.localizedDescription ?
            error.localizedDescription :
            @"Failed to serialize LevelPlay callback payload.",
        @"error",
        nil];
    NSError* fallbackError = nil;
    NSString* fallbackJson = JSONString(fallback, &fallbackError);
    AddToQueueCallback(message,
                       EVENT_JSON_ERROR,
                       handle,
                       fallbackJson ? fallbackJson.UTF8String :
                                      "{\"error\":\"Failed to serialize callback payload.\"}");
}

static void SendBridgeError(int message,
                            int event,
                            int handle,
                            int errorCode,
                            NSString* errorMessage,
                            NSString* operation)
{
    NSMutableDictionary* dictionary = [NSMutableDictionary dictionary];
    [dictionary setObject:[NSNumber numberWithInt:errorCode] forKey:@"error_code"];
    SetIfPresent(dictionary, @"error_message", errorMessage);
    SetIfPresent(dictionary, @"operation", operation);
    SendDictionary(message, event, handle, dictionary);
}

static bool ConfigureAPS()
{
    if (!s_APSEnabled || s_APSConfigured)
    {
        return true;
    }

    NSString* appId = RequiredString(s_APSAppId.c_str());
    if (!appId)
    {
        SendBridgeError(MSG_INIT,
                        EVENT_INIT_FAILED,
                        0,
                        ERROR_NETWORK_CONFIGURATION,
                        @"aps_ios_app_id is required when aps_ios is enabled.",
                        @"configure_aps");
        return false;
    }

    @try
    {
        Class apsClass = NSClassFromString(@"DTBAds");
        SEL sharedSelector = @selector(sharedInstance);
        SEL appKeySelector = NSSelectorFromString(@"setAppKey:");
        if (!apsClass ||
            ![(id)apsClass respondsToSelector:sharedSelector])
        {
            SendBridgeError(MSG_INIT,
                            EVENT_INIT_FAILED,
                            0,
                            ERROR_NETWORK_CONFIGURATION,
                            @"The Amazon Publisher Services SDK is not linked.",
                            @"configure_aps");
            return false;
        }

        id shared =
            ((id (*)(id, SEL))objc_msgSend)((id)apsClass, sharedSelector);
        if (!shared || ![shared respondsToSelector:appKeySelector])
        {
            SendBridgeError(MSG_INIT,
                            EVENT_INIT_FAILED,
                            0,
                            ERROR_NETWORK_CONFIGURATION,
                            @"The Amazon Publisher Services SDK does not expose setAppKey:.",
                            @"configure_aps");
            return false;
        }
        ((void (*)(id, SEL, NSString*))objc_msgSend)(
            shared, appKeySelector, appId);
    }
    @catch (NSException* exception)
    {
        SendBridgeError(MSG_INIT,
                        EVENT_INIT_FAILED,
                        0,
                        ERROR_NETWORK_CONFIGURATION,
                        exception.reason,
                        @"configure_aps");
        return false;
    }

    s_APSConfigured = true;
    return true;
}

static void SendInvalidHandle(int message,
                              int event,
                              int handle,
                              NSString* operation)
{
    SendBridgeError(message,
                    event,
                    handle,
                    ERROR_INVALID_HANDLE,
                    @"Unknown or destroyed LevelPlay ad handle.",
                    operation);
}

static bool CanCreateAd(int message, NSString* adUnitId, NSString* operation)
{
    if (!s_Initialized)
    {
        SendBridgeError(message,
                        EVENT_AD_LOAD_FAILED,
                        0,
                        ERROR_NOT_INITIALIZED,
                        @"Create ad units only after EVENT_INIT_SUCCEEDED.",
                        operation);
        return false;
    }
    if (!adUnitId)
    {
        SendBridgeError(message,
                        EVENT_AD_LOAD_FAILED,
                        0,
                        ERROR_INVALID_ARGUMENT,
                        @"The LevelPlay ad unit ID must not be empty.",
                        operation);
        return false;
    }
    return true;
}

static void SendAdInfo(int message, int event, int handle, LPMAdInfo* adInfo)
{
    SendDictionary(message, event, handle, AdInfoDictionary(adInfo));
}

static void SendLoadError(int message,
                          int handle,
                          NSString* adUnitId,
                          NSError* error)
{
    NSMutableDictionary* dictionary = [NSMutableDictionary dictionary];
    SetIfPresent(dictionary, @"ad_unit_id", adUnitId);
    AddError(dictionary, error);
    SendDictionary(message, EVENT_AD_LOAD_FAILED, handle, dictionary);
}

static void SendDisplayError(int message,
                             int handle,
                             LPMAdInfo* adInfo,
                             NSError* error)
{
    NSMutableDictionary* dictionary = AdInfoDictionary(adInfo);
    AddError(dictionary, error);
    SendDictionary(message, EVENT_AD_DISPLAY_FAILED, handle, dictionary);
}

static LPMAdSize* BannerAdSize(int size, UIViewController* viewController, bool respectSafeArea)
{
    switch (size)
    {
        case BANNER_SIZE_LARGE:
            return [LPMAdSize largeSize];
        case BANNER_SIZE_MEDIUM_RECTANGLE:
            return [LPMAdSize mediumRectangleSize];
        case BANNER_SIZE_LEADERBOARD:
            return [LPMAdSize leaderBoardSize];
        case BANNER_SIZE_ADAPTIVE:
        {
            CGFloat width = 0.0;
            if (viewController)
            {
                UIView* view = viewController.view;
                width = respectSafeArea ? view.safeAreaLayoutGuide.layoutFrame.size.width :
                                          view.bounds.size.width;
            }
            LPMAdSize* adaptiveSize = width > 0.0 ?
                [LPMAdSize createAdaptiveAdSizeWithWidth:width] :
                [LPMAdSize createAdaptiveAdSize];
            return adaptiveSize ? adaptiveSize : [LPMAdSize bannerSize];
        }
        case BANNER_SIZE_BANNER:
        default:
            return [LPMAdSize bannerSize];
    }
}

static void RemoveBannerConstraints(NSNumber* key)
{
    NSArray* constraints = [s_BannerConstraints objectForKey:key];
    if (constraints)
    {
        [NSLayoutConstraint deactivateConstraints:constraints];
        [s_BannerConstraints removeObjectForKey:key];
    }
}

static void AttachBanner(int handle)
{
    NSNumber* key = HandleKey(handle);
    LPMBannerAdView* banner = [s_BannerAds objectForKey:key];
    LPMAdSize* size = [s_BannerSizes objectForKey:key];
    UIViewController* viewController = CurrentRootViewController();
    if (!banner || !size || !viewController)
    {
        return;
    }

    UIView* container = viewController.view;
    if (banner.superview != container)
    {
        RemoveBannerConstraints(key);
        [banner removeFromSuperview];
        [container addSubview:banner];
    }

    RemoveBannerConstraints(key);
    banner.translatesAutoresizingMaskIntoConstraints = NO;

    BOOL respectSafeArea = [[s_BannerSafeAreas objectForKey:key] boolValue];
    int position = [[s_BannerPositions objectForKey:key] intValue];
    UILayoutGuide* safeArea = container.safeAreaLayoutGuide;

    NSLayoutConstraint* verticalConstraint = nil;
    if (position == BANNER_POSITION_TOP)
    {
        verticalConstraint = respectSafeArea ?
            [banner.topAnchor constraintEqualToAnchor:safeArea.topAnchor] :
            [banner.topAnchor constraintEqualToAnchor:container.topAnchor];
    }
    else
    {
        verticalConstraint = respectSafeArea ?
            [banner.bottomAnchor constraintEqualToAnchor:safeArea.bottomAnchor] :
            [banner.bottomAnchor constraintEqualToAnchor:container.bottomAnchor];
    }

    NSArray* constraints = [NSArray arrayWithObjects:
        [banner.centerXAnchor constraintEqualToAnchor:container.centerXAnchor],
        [banner.widthAnchor constraintEqualToConstant:(CGFloat)size.width],
        [banner.heightAnchor constraintEqualToConstant:(CGFloat)size.height],
        verticalConstraint,
        nil];
    [NSLayoutConstraint activateConstraints:constraints];
    [s_BannerConstraints setObject:constraints forKey:key];
}

void Initialize_Ext(const char* engineVersion,
                    const char* extensionVersion,
                    bool apsEnabled,
                    const char* apsAppId)
{
    (void)engineVersion;
    (void)extensionVersion;
    s_APSEnabled = apsEnabled;
    s_APSConfigured = false;
    s_APSAppId = apsAppId ? apsAppId : "";
    RunOnMainSync(^{
        ++s_LifetimeGeneration;
        if (s_LifetimeGeneration == 0)
        {
            ++s_LifetimeGeneration;
        }
        s_Active = true;
        EnsureStorage();
        CurrentRootViewController();
    });
}

void Finalize_Ext()
{
    RunOnMainSync(^{
        NSArray* bannerKeys = [[s_BannerAds allKeys] copy];
        for (NSNumber* key in bannerKeys)
        {
            LPMBannerAdView* ad = [s_BannerAds objectForKey:key];
            [ad destroy];
            RemoveBannerConstraints(key);
            [ad removeFromSuperview];
        }
        [bannerKeys release];

        [s_InterstitialDelegates removeAllObjects];
        [s_InterstitialAds removeAllObjects];
        [s_RewardedDelegates removeAllObjects];
        [s_RewardedAds removeAllObjects];
        [s_BannerDelegates removeAllObjects];
        [s_BannerSizes removeAllObjects];
        [s_BannerPositions removeAllObjects];
        [s_BannerSafeAreas removeAllObjects];
        [s_BannerConstraints removeAllObjects];
        [s_BannerAds removeAllObjects];

        [s_InterstitialAds release];
        [s_InterstitialDelegates release];
        [s_RewardedAds release];
        [s_RewardedDelegates release];
        [s_BannerAds release];
        [s_BannerDelegates release];
        [s_BannerSizes release];
        [s_BannerPositions release];
        [s_BannerSafeAreas release];
        [s_BannerConstraints release];

        s_InterstitialAds = nil;
        s_InterstitialDelegates = nil;
        s_RewardedAds = nil;
        s_RewardedDelegates = nil;
        s_BannerAds = nil;
        s_BannerDelegates = nil;
        s_BannerSizes = nil;
        s_BannerPositions = nil;
        s_BannerSafeAreas = nil;
        s_BannerConstraints = nil;
        s_Initialized = false;
        s_Initializing = false;
        s_APSEnabled = false;
        s_APSConfigured = false;
        s_APSAppId.clear();
        s_Active = false;
        s_NextHandle = 1;
        s_StringResult.clear();
        ++s_LifetimeGeneration;
        if (s_LifetimeGeneration == 0)
        {
            ++s_LifetimeGeneration;
        }
    });
}

void Init(const char* appKey, const char* userId)
{
    RunOnMainSync(^{
        EnsureStorage();
        NSString* appKeyString = RequiredString(appKey);
        if (!appKeyString)
        {
            SendBridgeError(MSG_INIT,
                            EVENT_INIT_FAILED,
                            0,
                            ERROR_INVALID_ARGUMENT,
                            @"The LevelPlay app key must not be empty.",
                            @"init");
            return;
        }
        if (s_Initializing || s_Initialized)
        {
            SendBridgeError(MSG_INIT,
                            EVENT_INIT_FAILED,
                            0,
                            ERROR_INVALID_ARGUMENT,
                            @"LevelPlay initialization has already started.",
                            @"init");
            return;
        }
        if (!ConfigureAPS())
        {
            return;
        }

        s_Initialized = false;
        s_Initializing = true;
        @try
        {
            LPMInitRequestBuilder* builder =
                [[[LPMInitRequestBuilder alloc] initWithAppKey:appKeyString] autorelease];
            NSString* userIdString = OptionalString(userId);
            if (userIdString)
            {
                [builder withUserId:userIdString];
            }
            LPMInitRequest* request = [builder build];
            const unsigned int generation = s_LifetimeGeneration;

            [LevelPlay initWithRequest:request completion:^(LPMConfiguration* configuration,
                                                            NSError* error) {
                RunOnMainAsync(^{
                    if (!s_Active || generation != s_LifetimeGeneration)
                    {
                        return;
                    }
                    s_Initializing = false;
                    if (error)
                    {
                        s_Initialized = false;
                        NSMutableDictionary* dictionary =
                            [NSMutableDictionary dictionary];
                        AddError(dictionary, error);
                        SendDictionary(MSG_INIT, EVENT_INIT_FAILED, 0, dictionary);
                    }
                    else
                    {
                        s_Initialized = true;
                        NSMutableDictionary* dictionary =
                            [NSMutableDictionary dictionary];
                        if (configuration)
                        {
                            [dictionary setObject:
                                [NSNumber numberWithBool:configuration.isAdQualityEnabled]
                                            forKey:@"ad_quality_enabled"];
                            SetIfPresent(dictionary, @"ab", configuration.ab);
                        }
                        SendDictionary(MSG_INIT, EVENT_INIT_SUCCEEDED, 0, dictionary);
                    }
                });
            }];
        }
        @catch (NSException* exception)
        {
            s_Initializing = false;
            s_Initialized = false;
            SendBridgeError(MSG_INIT,
                            EVENT_INIT_FAILED,
                            0,
                            ERROR_SDK_EXCEPTION,
                            exception.reason,
                            @"init");
        }
    });
}

const char* GetSdkVersion()
{
    RunOnMainSync(^{
        NSString* version = [LevelPlay sdkVersion];
        s_StringResult = version ? version.UTF8String : "";
    });
    return s_StringResult.c_str();
}

void ValidateIntegration()
{
    RunOnMainSync(^{
        [LevelPlay validateIntegration];
    });
}

void LaunchTestSuite()
{
    RunOnMainSync(^{
        UIViewController* viewController = PresentationViewController();
        if (viewController)
        {
            [LevelPlay launchTestSuite:viewController];
        }
    });
}

void SetGDPRConsent(bool consent)
{
    RunOnMainSync(^{
        [LPMPrivacySettings setGDPRConsent:consent ? YES : NO];
    });
}

void SetCCPA(bool optedOut)
{
    RunOnMainSync(^{
        [LPMPrivacySettings setCCPA:optedOut ? YES : NO];
    });
}

void SetCOPPA(bool childDirected)
{
    RunOnMainSync(^{
        if (s_Initializing || s_Initialized)
        {
            dmLogError("LevelPlay COPPA must be set before initialization.");
            return;
        }
        [LPMPrivacySettings setCOPPA:childDirected ? YES : NO];
    });
}

void SetMetaData(const char* key, const char* value)
{
    RunOnMainSync(^{
        NSString* keyString = RequiredString(key);
        NSString* valueString = RequiredString(value);
        if (keyString && valueString)
        {
            [LevelPlay setMetaDataWithKey:keyString value:valueString];
        }
    });
}

bool SetMetaLimitedDataUse(bool enabled, int country, int state)
{
    __block BOOL applied = NO;
    RunOnMainSync(^{
        if (s_Initializing || s_Initialized || !s_Active)
        {
            return;
        }
        Class settings = NSClassFromString(@"FBAdSettings");
        if (!settings)
        {
            return;
        }

        @try
        {
            NSArray* options = enabled ?
                [NSArray arrayWithObject:@"LDU"] :
                [NSArray array];
            if (enabled)
            {
                SEL selector =
                    NSSelectorFromString(@"setDataProcessingOptions:country:state:");
                if (![(id)settings respondsToSelector:selector])
                {
                    return;
                }
                ((void (*)(id, SEL, NSArray*, NSInteger, NSInteger))objc_msgSend)(
                    (id)settings,
                    selector,
                    options,
                    (NSInteger)country,
                    (NSInteger)state);
            }
            else
            {
                SEL selector = NSSelectorFromString(@"setDataProcessingOptions:");
                if (![(id)settings respondsToSelector:selector])
                {
                    return;
                }
                ((void (*)(id, SEL, NSArray*))objc_msgSend)(
                    (id)settings, selector, options);
            }
            applied = YES;
        }
        @catch (NSException* exception)
        {
            dmLogError("Unable to configure Meta Limited Data Use: %s",
                       exception.reason.UTF8String);
        }
    });
    return applied == YES;
}

bool SetMetaAdvertiserTracking(bool enabled)
{
    __block BOOL applied = NO;
    RunOnMainSync(^{
        if (s_Initializing || s_Initialized || !s_Active)
        {
            return;
        }
        Class settings = NSClassFromString(@"FBAdSettings");
        SEL selector = NSSelectorFromString(@"setAdvertiserTrackingEnabled:");
        if (!settings || ![(id)settings respondsToSelector:selector])
        {
            return;
        }
        @try
        {
            ((void (*)(id, SEL, BOOL))objc_msgSend)(
                (id)settings, selector, enabled ? YES : NO);
            applied = YES;
        }
        @catch (NSException* exception)
        {
            dmLogError("Unable to configure Meta advertiser tracking: %s",
                       exception.reason.UTF8String);
        }
    });
    return applied == YES;
}

bool SetDynamicUserId(const char* userId)
{
    __block BOOL result = NO;
    RunOnMainSync(^{
        NSString* userIdString = RequiredString(userId);
        if (userIdString)
        {
            result = [LevelPlay setDynamicUserId:userIdString];
        }
    });
    return result == YES;
}

void SetAdaptersDebug(bool enabled)
{
    RunOnMainSync(^{
        [LevelPlay setAdaptersDebug:enabled ? YES : NO];
    });
}

bool IsTrackingAuthorizationSupported()
{
#if __has_include(<AppTrackingTransparency/ATTrackingManager.h>)
    if (@available(iOS 14, *))
    {
        return true;
    }
#endif
    return false;
}

static int TrackingAuthorizationStatus()
{
#if __has_include(<AppTrackingTransparency/ATTrackingManager.h>)
    if (@available(iOS 14, *))
    {
        switch ([ATTrackingManager trackingAuthorizationStatus])
        {
            case ATTrackingManagerAuthorizationStatusAuthorized:
                return TRACKING_STATUS_AUTHORIZED;
            case ATTrackingManagerAuthorizationStatusDenied:
                return TRACKING_STATUS_DENIED;
            case ATTrackingManagerAuthorizationStatusNotDetermined:
                return TRACKING_STATUS_NOT_DETERMINED;
            case ATTrackingManagerAuthorizationStatusRestricted:
                return TRACKING_STATUS_RESTRICTED;
        }
    }
#endif
    return -1;
}

void RequestTrackingAuthorization()
{
#if __has_include(<AppTrackingTransparency/ATTrackingManager.h>)
    RunOnMainAsync(^{
        if (@available(iOS 14, *))
        {
            [ATTrackingManager
                requestTrackingAuthorizationWithCompletionHandler:
                    ^(ATTrackingManagerAuthorizationStatus status) {
                        int event = TRACKING_STATUS_RESTRICTED;
                        switch (status)
                        {
                            case ATTrackingManagerAuthorizationStatusAuthorized:
                                event = TRACKING_STATUS_AUTHORIZED;
                                break;
                            case ATTrackingManagerAuthorizationStatusDenied:
                                event = TRACKING_STATUS_DENIED;
                                break;
                            case ATTrackingManagerAuthorizationStatusNotDetermined:
                                event = TRACKING_STATUS_NOT_DETERMINED;
                                break;
                            case ATTrackingManagerAuthorizationStatusRestricted:
                                event = TRACKING_STATUS_RESTRICTED;
                                break;
                        }
                        RunOnMainAsync(^{
                            if (s_Active)
                            {
                                AddToQueueCallback(MSG_TRACKING, event, 0, "{}");
                            }
                        });
                    }];
        }
    });
#endif
}

int GetTrackingAuthorizationStatus()
{
    __block int status = -1;
    RunOnMainSync(^{
        status = TrackingAuthorizationStatus();
    });
    return status;
}

int CreateInterstitialAd(const char* adUnitId, double bidFloor)
{
    __block int handle = 0;
    RunOnMainSync(^{
        EnsureStorage();
        NSString* adUnitIdString = RequiredString(adUnitId);
        if (!CanCreateAd(MSG_INTERSTITIAL, adUnitIdString, @"create_interstitial"))
        {
            return;
        }

        handle = AllocateHandle();
        LPMInterstitialAd* ad = nil;
        if (bidFloor >= 0.0 && std::isfinite(bidFloor))
        {
            LPMInterstitialAdConfigBuilder* builder =
                [[[LPMInterstitialAdConfigBuilder alloc] init] autorelease];
            [builder setWithBidFloor:[NSNumber numberWithDouble:bidFloor]];
            ad = [[LPMInterstitialAd alloc] initWithAdUnitId:adUnitIdString
                                                     config:[builder build]];
        }
        else
        {
            ad = [[LPMInterstitialAd alloc] initWithAdUnitId:adUnitIdString];
        }

        DMLevelPlayInterstitialDelegate* delegate =
            [[DMLevelPlayInterstitialDelegate alloc] initWithHandle:handle];
        [ad setDelegate:delegate];

        NSNumber* key = HandleKey(handle);
        [s_InterstitialAds setObject:ad forKey:key];
        [s_InterstitialDelegates setObject:delegate forKey:key];
        [ad release];
        [delegate release];
    });
    return handle;
}

void DestroyInterstitialAd(int handle)
{
    RunOnMainSync(^{
        NSNumber* key = HandleKey(handle);
        LPMInterstitialAd* ad = [s_InterstitialAds objectForKey:key];
        [ad setDelegate:nil];
        [s_InterstitialDelegates removeObjectForKey:key];
        [s_InterstitialAds removeObjectForKey:key];
    });
}

void LoadInterstitialAd(int handle)
{
    RunOnMainSync(^{
        LPMInterstitialAd* ad = [s_InterstitialAds objectForKey:HandleKey(handle)];
        if (!ad)
        {
            SendInvalidHandle(MSG_INTERSTITIAL,
                              EVENT_AD_LOAD_FAILED,
                              handle,
                              @"load_interstitial");
            return;
        }
        [ad loadAd];
    });
}

bool IsInterstitialAdReady(int handle)
{
    __block BOOL ready = NO;
    RunOnMainSync(^{
        ready = [[s_InterstitialAds objectForKey:HandleKey(handle)] isAdReady];
    });
    return ready == YES;
}

void ShowInterstitialAd(int handle, const char* placementName)
{
    RunOnMainSync(^{
        LPMInterstitialAd* ad = [s_InterstitialAds objectForKey:HandleKey(handle)];
        UIViewController* viewController = PresentationViewController();
        if (!ad)
        {
            SendInvalidHandle(MSG_INTERSTITIAL,
                              EVENT_AD_DISPLAY_FAILED,
                              handle,
                              @"show_interstitial");
            return;
        }
        if (!viewController)
        {
            SendBridgeError(MSG_INTERSTITIAL,
                            EVENT_AD_DISPLAY_FAILED,
                            handle,
                            ERROR_NO_VIEW_CONTROLLER,
                            @"No iOS view controller is available to present the ad.",
                            @"show_interstitial");
            return;
        }
        else
        {
            [ad showAdWithViewController:viewController
                           placementName:OptionalString(placementName)];
        }
    });
}

bool IsInterstitialPlacementCapped(const char* placementName)
{
    __block BOOL capped = NO;
    RunOnMainSync(^{
        NSString* placement = RequiredString(placementName);
        if (placement)
        {
            capped = [LPMInterstitialAd isPlacementCapped:placement];
        }
    });
    return capped == YES;
}

int CreateRewardedAd(const char* adUnitId, double bidFloor)
{
    __block int handle = 0;
    RunOnMainSync(^{
        EnsureStorage();
        NSString* adUnitIdString = RequiredString(adUnitId);
        if (!CanCreateAd(MSG_REWARDED, adUnitIdString, @"create_rewarded"))
        {
            return;
        }

        handle = AllocateHandle();
        LPMRewardedAd* ad = nil;
        if (bidFloor >= 0.0 && std::isfinite(bidFloor))
        {
            LPMRewardedAdConfigBuilder* builder =
                [[[LPMRewardedAdConfigBuilder alloc] init] autorelease];
            [builder setWithBidFloor:[NSNumber numberWithDouble:bidFloor]];
            ad = [[LPMRewardedAd alloc] initWithAdUnitId:adUnitIdString
                                                 config:[builder build]];
        }
        else
        {
            ad = [[LPMRewardedAd alloc] initWithAdUnitId:adUnitIdString];
        }

        DMLevelPlayRewardedDelegate* delegate =
            [[DMLevelPlayRewardedDelegate alloc] initWithHandle:handle];
        [ad setDelegate:delegate];

        NSNumber* key = HandleKey(handle);
        [s_RewardedAds setObject:ad forKey:key];
        [s_RewardedDelegates setObject:delegate forKey:key];
        [ad release];
        [delegate release];
    });
    return handle;
}

void DestroyRewardedAd(int handle)
{
    RunOnMainSync(^{
        NSNumber* key = HandleKey(handle);
        LPMRewardedAd* ad = [s_RewardedAds objectForKey:key];
        [ad setDelegate:nil];
        [s_RewardedDelegates removeObjectForKey:key];
        [s_RewardedAds removeObjectForKey:key];
    });
}

void LoadRewardedAd(int handle)
{
    RunOnMainSync(^{
        LPMRewardedAd* ad = [s_RewardedAds objectForKey:HandleKey(handle)];
        if (!ad)
        {
            SendInvalidHandle(MSG_REWARDED,
                              EVENT_AD_LOAD_FAILED,
                              handle,
                              @"load_rewarded");
            return;
        }
        [ad loadAd];
    });
}

bool IsRewardedAdReady(int handle)
{
    __block BOOL ready = NO;
    RunOnMainSync(^{
        ready = [[s_RewardedAds objectForKey:HandleKey(handle)] isAdReady];
    });
    return ready == YES;
}

void ShowRewardedAd(int handle, const char* placementName)
{
    RunOnMainSync(^{
        LPMRewardedAd* ad = [s_RewardedAds objectForKey:HandleKey(handle)];
        UIViewController* viewController = PresentationViewController();
        if (!ad)
        {
            SendInvalidHandle(MSG_REWARDED,
                              EVENT_AD_DISPLAY_FAILED,
                              handle,
                              @"show_rewarded");
            return;
        }
        if (!viewController)
        {
            SendBridgeError(MSG_REWARDED,
                            EVENT_AD_DISPLAY_FAILED,
                            handle,
                            ERROR_NO_VIEW_CONTROLLER,
                            @"No iOS view controller is available to present the ad.",
                            @"show_rewarded");
            return;
        }
        else
        {
            [ad showAdWithViewController:viewController
                           placementName:OptionalString(placementName)];
        }
    });
}

bool IsRewardedPlacementCapped(const char* placementName)
{
    __block BOOL capped = NO;
    RunOnMainSync(^{
        NSString* placement = RequiredString(placementName);
        if (placement)
        {
            capped = [LPMRewardedAd isPlacementCapped:placement];
        }
    });
    return capped == YES;
}

const char* GetReward(int handle, const char* placementName)
{
    __block bool valid = false;
    RunOnMainSync(^{
        LPMRewardedAd* ad = [s_RewardedAds objectForKey:HandleKey(handle)];
        if (!ad)
        {
            return;
        }
        LPMReward* reward = [ad getRewardWithPlacementName:OptionalString(placementName)];
        if (!reward)
        {
            return;
        }
        valid = true;
        NSDictionary* dictionary = [NSDictionary dictionaryWithObjectsAndKeys:
            reward.name ? reward.name : @"", @"name",
            [NSNumber numberWithInteger:reward.amount], @"amount",
            nil];
        NSError* error = nil;
        NSString* json = JSONString(dictionary, &error);
        s_StringResult = json ? json.UTF8String : "{\"name\":\"\",\"amount\":0}";
    });
    return valid ? s_StringResult.c_str() : NULL;
}

int CreateBannerAd(const char* adUnitId,
                   int size,
                   int position,
                   const char* placementName,
                   double bidFloor,
                   bool respectSafeArea)
{
    __block int handle = 0;
    RunOnMainSync(^{
        EnsureStorage();
        NSString* adUnitIdString = RequiredString(adUnitId);
        UIViewController* viewController = CurrentRootViewController();
        if (!CanCreateAd(MSG_BANNER, adUnitIdString, @"create_banner"))
        {
            return;
        }
        if (position != BANNER_POSITION_TOP && position != BANNER_POSITION_BOTTOM)
        {
            SendBridgeError(MSG_BANNER,
                            EVENT_AD_LOAD_FAILED,
                            0,
                            ERROR_INVALID_ARGUMENT,
                            @"Banner position must be top (1) or bottom (2).",
                            @"create_banner");
            return;
        }
        if (!viewController)
        {
            SendBridgeError(MSG_BANNER,
                            EVENT_AD_LOAD_FAILED,
                            0,
                            ERROR_NO_VIEW_CONTROLLER,
                            @"No iOS view controller is available to attach the banner.",
                            @"create_banner");
            return;
        }

        handle = AllocateHandle();
        LPMAdSize* adSize = BannerAdSize(size, viewController, respectSafeArea);
        LPMBannerAdViewConfigBuilder* builder =
            [[[LPMBannerAdViewConfigBuilder alloc] init] autorelease];
        [builder setWithAdSize:adSize];
        NSString* placement = OptionalString(placementName);
        if (placement)
        {
            [builder setWithPlacementName:placement];
        }
        if (bidFloor >= 0.0 && std::isfinite(bidFloor))
        {
            [builder setWithBidFloor:[NSNumber numberWithDouble:bidFloor]];
        }

        LPMBannerAdView* ad = [[LPMBannerAdView alloc] initWithAdUnitId:adUnitIdString
                                                                config:[builder build]];
        DMLevelPlayBannerDelegate* delegate =
            [[DMLevelPlayBannerDelegate alloc] initWithHandle:handle];
        [ad setDelegate:delegate];
        // Native LevelPlay banner loading is also the display path. Keep the
        // attached view visible by default; hide/show remain useful after a
        // successful load.
        ad.hidden = NO;

        NSNumber* key = HandleKey(handle);
        [s_BannerAds setObject:ad forKey:key];
        [s_BannerDelegates setObject:delegate forKey:key];
        [s_BannerSizes setObject:adSize forKey:key];
        [s_BannerPositions setObject:
            [NSNumber numberWithInt:position == BANNER_POSITION_TOP ?
                                      BANNER_POSITION_TOP :
                                      BANNER_POSITION_BOTTOM]
                                   forKey:key];
        [s_BannerSafeAreas setObject:[NSNumber numberWithBool:respectSafeArea]
                              forKey:key];
        AttachBanner(handle);

        [ad release];
        [delegate release];
    });
    return handle;
}

void LoadBannerAd(int handle)
{
    RunOnMainSync(^{
        LPMBannerAdView* ad = [s_BannerAds objectForKey:HandleKey(handle)];
        UIViewController* viewController = CurrentRootViewController();
        if (ad && viewController)
        {
            AttachBanner(handle);
            [ad loadAdWithViewController:viewController];
        }
        else if (!ad)
        {
            SendInvalidHandle(MSG_BANNER,
                              EVENT_AD_LOAD_FAILED,
                              handle,
                              @"load_banner");
        }
        else
        {
            SendBridgeError(MSG_BANNER,
                            EVENT_AD_LOAD_FAILED,
                            handle,
                            ERROR_NO_VIEW_CONTROLLER,
                            @"No iOS view controller is available to load the banner.",
                            @"load_banner");
        }
    });
}

void ShowBannerAd(int handle)
{
    RunOnMainSync(^{
        LPMBannerAdView* ad = [s_BannerAds objectForKey:HandleKey(handle)];
        UIViewController* viewController = CurrentRootViewController();
        if (ad && viewController)
        {
            AttachBanner(handle);
            ad.hidden = NO;
        }
        else if (!ad)
        {
            SendInvalidHandle(MSG_BANNER,
                              EVENT_AD_DISPLAY_FAILED,
                              handle,
                              @"show_banner");
        }
        else
        {
            SendBridgeError(MSG_BANNER,
                            EVENT_AD_DISPLAY_FAILED,
                            handle,
                            ERROR_NO_VIEW_CONTROLLER,
                            @"No iOS view controller is available to show the banner.",
                            @"show_banner");
        }
    });
}

void HideBannerAd(int handle)
{
    RunOnMainSync(^{
        LPMBannerAdView* ad = [s_BannerAds objectForKey:HandleKey(handle)];
        if (ad)
        {
            ad.hidden = YES;
        }
        else
        {
            SendInvalidHandle(MSG_BANNER,
                              EVENT_AD_DISPLAY_FAILED,
                              handle,
                              @"hide_banner");
        }
    });
}

void PauseBannerAutoRefresh(int handle)
{
    RunOnMainSync(^{
        LPMBannerAdView* ad = [s_BannerAds objectForKey:HandleKey(handle)];
        if (ad)
        {
            [ad pauseAutoRefresh];
        }
        else
        {
            SendInvalidHandle(MSG_BANNER,
                              EVENT_AD_DISPLAY_FAILED,
                              handle,
                              @"pause_banner");
        }
    });
}

void ResumeBannerAutoRefresh(int handle)
{
    RunOnMainSync(^{
        LPMBannerAdView* ad = [s_BannerAds objectForKey:HandleKey(handle)];
        if (ad)
        {
            [ad resumeAutoRefresh];
        }
        else
        {
            SendInvalidHandle(MSG_BANNER,
                              EVENT_AD_DISPLAY_FAILED,
                              handle,
                              @"resume_banner");
        }
    });
}

void DestroyBannerAd(int handle)
{
    RunOnMainSync(^{
        NSNumber* key = HandleKey(handle);
        LPMBannerAdView* ad = [s_BannerAds objectForKey:key];
        if (ad)
        {
            [ad destroy];
            RemoveBannerConstraints(key);
            [ad removeFromSuperview];
        }
        [s_BannerDelegates removeObjectForKey:key];
        [s_BannerSizes removeObjectForKey:key];
        [s_BannerPositions removeObjectForKey:key];
        [s_BannerSafeAreas removeObjectForKey:key];
        [s_BannerAds removeObjectForKey:key];
    });
}

} // namespace dmLevelPlay

@implementation DMLevelPlayInterstitialDelegate

- (instancetype)initWithHandle:(int)handle
{
    self = [super init];
    if (self)
    {
        m_Handle = handle;
    }
    return self;
}

- (void)didLoadAdWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_INTERSTITIAL,
                            dmLevelPlay::EVENT_AD_LOADED,
                            m_Handle,
                            adInfo);
}

- (void)didFailToLoadAdWithAdUnitId:(NSString*)adUnitId error:(NSError*)error
{
    dmLevelPlay::SendLoadError(dmLevelPlay::MSG_INTERSTITIAL,
                               m_Handle,
                               adUnitId,
                               error);
}

- (void)didDisplayAdWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_INTERSTITIAL,
                            dmLevelPlay::EVENT_AD_DISPLAYED,
                            m_Handle,
                            adInfo);
}

- (void)didFailToDisplayAdWithAdInfo:(LPMAdInfo*)adInfo error:(NSError*)error
{
    dmLevelPlay::SendDisplayError(dmLevelPlay::MSG_INTERSTITIAL,
                                  m_Handle,
                                  adInfo,
                                  error);
}

- (void)didClickAdWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_INTERSTITIAL,
                            dmLevelPlay::EVENT_AD_CLICKED,
                            m_Handle,
                            adInfo);
}

- (void)didCloseAdWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_INTERSTITIAL,
                            dmLevelPlay::EVENT_AD_CLOSED,
                            m_Handle,
                            adInfo);
}

- (void)didChangeAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_INTERSTITIAL,
                            dmLevelPlay::EVENT_AD_INFO_CHANGED,
                            m_Handle,
                            adInfo);
}

@end

@implementation DMLevelPlayRewardedDelegate

- (instancetype)initWithHandle:(int)handle
{
    self = [super init];
    if (self)
    {
        m_Handle = handle;
    }
    return self;
}

- (void)didLoadAdWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_REWARDED,
                            dmLevelPlay::EVENT_AD_LOADED,
                            m_Handle,
                            adInfo);
}

- (void)didFailToLoadAdWithAdUnitId:(NSString*)adUnitId error:(NSError*)error
{
    dmLevelPlay::SendLoadError(dmLevelPlay::MSG_REWARDED,
                               m_Handle,
                               adUnitId,
                               error);
}

- (void)didDisplayAdWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_REWARDED,
                            dmLevelPlay::EVENT_AD_DISPLAYED,
                            m_Handle,
                            adInfo);
}

- (void)didRewardAdWithAdInfo:(LPMAdInfo*)adInfo reward:(LPMReward*)reward
{
    NSMutableDictionary* dictionary = dmLevelPlay::AdInfoDictionary(adInfo);
    if (reward)
    {
        dmLevelPlay::SetIfPresent(dictionary, @"reward_name", reward.name);
        [dictionary setObject:[NSNumber numberWithInteger:reward.amount]
                       forKey:@"reward_amount"];
    }
    dmLevelPlay::SendDictionary(dmLevelPlay::MSG_REWARDED,
                                dmLevelPlay::EVENT_AD_REWARDED,
                                m_Handle,
                                dictionary);
}

- (void)didFailToDisplayAdWithAdInfo:(LPMAdInfo*)adInfo error:(NSError*)error
{
    dmLevelPlay::SendDisplayError(dmLevelPlay::MSG_REWARDED,
                                  m_Handle,
                                  adInfo,
                                  error);
}

- (void)didClickAdWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_REWARDED,
                            dmLevelPlay::EVENT_AD_CLICKED,
                            m_Handle,
                            adInfo);
}

- (void)didCloseAdWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_REWARDED,
                            dmLevelPlay::EVENT_AD_CLOSED,
                            m_Handle,
                            adInfo);
}

- (void)didChangeAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_REWARDED,
                            dmLevelPlay::EVENT_AD_INFO_CHANGED,
                            m_Handle,
                            adInfo);
}

@end

@implementation DMLevelPlayBannerDelegate

- (instancetype)initWithHandle:(int)handle
{
    self = [super init];
    if (self)
    {
        m_Handle = handle;
    }
    return self;
}

- (void)didLoadAdWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_BANNER,
                            dmLevelPlay::EVENT_AD_LOADED,
                            m_Handle,
                            adInfo);
}

- (void)didFailToLoadAdWithAdUnitId:(NSString*)adUnitId error:(NSError*)error
{
    dmLevelPlay::SendLoadError(dmLevelPlay::MSG_BANNER,
                               m_Handle,
                               adUnitId,
                               error);
}

- (void)didClickAdWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_BANNER,
                            dmLevelPlay::EVENT_AD_CLICKED,
                            m_Handle,
                            adInfo);
}

- (void)didDisplayAdWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_BANNER,
                            dmLevelPlay::EVENT_AD_DISPLAYED,
                            m_Handle,
                            adInfo);
}

- (void)didFailToDisplayAdWithAdInfo:(LPMAdInfo*)adInfo error:(NSError*)error
{
    dmLevelPlay::SendDisplayError(dmLevelPlay::MSG_BANNER,
                                  m_Handle,
                                  adInfo,
                                  error);
}

- (void)didLeaveAppWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_BANNER,
                            dmLevelPlay::EVENT_AD_LEFT_APPLICATION,
                            m_Handle,
                            adInfo);
}

- (void)didExpandAdWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_BANNER,
                            dmLevelPlay::EVENT_AD_EXPANDED,
                            m_Handle,
                            adInfo);
}

- (void)didCollapseAdWithAdInfo:(LPMAdInfo*)adInfo
{
    dmLevelPlay::SendAdInfo(dmLevelPlay::MSG_BANNER,
                            dmLevelPlay::EVENT_AD_COLLAPSED,
                            m_Handle,
                            adInfo);
}

@end

#endif

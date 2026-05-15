/**
 * adminApi/appConfig.ts — Platform-wide app config (fees, labels,
 * extras, insurance, enable/cap toggles).
 *
 * The /admin/platform-fees screen consumes the AppConfig type and uses
 * the master `adminApi.getAppConfig() / updateAppConfig()` pair.
 */
export type {
  AppConfig,
  AdminPlatformFee,
  LegalPage,
} from './_legacy';

/**
 * adminApi/_legacy.ts — Backwards-compat composition of the master `adminApi`.
 *
 * Phase C of the June 2025 refactor (completed): the giant 1,400-line file
 * has been decomposed. Every method body now lives in its own domain module
 * (`./auth.ts`, `./users.ts`, `./groups.ts`, `./integrations.ts`, etc.).
 *
 * This file now serves ONE purpose: stitch the domain APIs back together
 * into the historical `adminApi.<method>` shape so existing consumer code
 * (~30 admin screens) keeps working without any import changes.
 *
 *   OLD code           // ✅ still works:
 *   adminApi.listUsers({ q: 'foo' })   →  usersApi.list({ q: 'foo' })
 *   adminApi.getIncomeFees()           →  incomeFeesApi.get()
 *   adminApi.setStripe({...})          →  integrationsApi.setStripe({...})
 *
 *   NEW code           // ✅ recommended:
 *   import { usersApi, integrationsApi } from '../../src/adminApi';
 *   usersApi.list({ q: 'foo' });
 *   integrationsApi.setStripe({...});
 *
 * Eventually consumers can migrate to the domain-scoped clients and this
 * shim can be deleted entirely.
 */
import { accessApi } from './access';
import { adminsApi } from './admins';
import { analyticsApi } from './analytics';
import { appConfigApi } from './appConfig';
import { auditApi } from './audit';
import { authApi } from './auth';
import { broadcastsApi } from './broadcasts';
import { contactMessagesApi } from './contactMessages';
import { creditRulesApi } from './creditRules';
import { featuresApi } from './features';
import { gatewaysApi } from './gateways';
import { groupsApi } from './groups';
import { incomeFeesApi } from './incomeFees';
import { integrationsApi } from './integrations';
import { kmsApi } from './security';
import { legalApi } from './legal';
import { masterCardApi } from './masterCard';
import { reconciliationApi } from './reconciliation';
import { referralsApi } from './referrals';
import { usersApi } from './users';

// Re-export session helpers + typed getProfile wrapper. These were always
// available from this barrel; consumers in `_layout.tsx`, `access.tsx`,
// `dashboard.tsx` import them by name.
export { getToken, clearSession, setSession, _aRequest, BACKEND_URL } from './_core';
import { getProfile as _getProfileRaw } from './_core';
import type { AdminProfile } from './admin';

/**
 * Typed admin-profile reader. Wraps the generic `_core.getProfile<T>()` so
 * callers don't need to specify the type parameter at every call site.
 */
export function getProfile(): Promise<AdminProfile | null> {
  return _getProfileRaw<AdminProfile>();
}

// Re-export every type that was historically importable from `adminApi`, now
// sourced from the domain modules they live in. Adds NO new exports;
// preserves existing import paths for ~30 admin screens.
export type {
  AdminRole,
  AdminProfile,
  AdminMetrics,
  AuditEntry,
  AdminUserRow,
  AdminUserDetail,
  AdminGroupRow,
  AdminGroupDetail,
} from './admin';
export type {
  IntegrationsView,
  StripeIn,
  TwilioIn,
  SignalWireIn,
  RemindersIn,
} from './integrations';
export type {
  ReconciliationSettings,
  ReconciliationRow,
  MasterAccountEntry,
} from './reconciliation';
export type {
  AppConfig,
  AdminPlatformFee,
} from './appConfig';
export type {
  ReferralSettings,
  ReferralStats,
  ReferrerRow,
  ReferrerDetail,
} from './referrals';
export type {
  GroupDiscount,
  LeadAutoDiscount,
  CreditRow,
  UserCreditWallet,
} from './rewards';
export type { AnalyticsPayload } from './analytics';
export type { KmsStatus, KmsRotateResult } from './security';
export type { LegalPage } from './legal';
export type { MasterCard } from './masterCard';

/**
 * Master admin API client — composed from per-domain modules.
 *
 * Each property is a thin alias to a domain method (no re-implementation,
 * no `request()` calls in this file anymore). Adding/removing methods now
 * happens in the corresponding domain file, not here.
 */
export const adminApi = {
  // ----- Auth + global lookups (./auth) -----
  login: authApi.login,
  me: authApi.me,
  changePassword: authApi.changePassword,
  logout: authApi.logout,
  metrics: authApi.metrics,
  search: authApi.search,

  // ----- Audit log (./audit) -----
  auditLog: auditApi.list,
  auditLogExportUrl: auditApi.exportUrl,
  downloadAuditCsv: auditApi.downloadCsv,

  // ----- Admin-user CRUD (./admins) -----
  listAdmins: adminsApi.list,
  createAdmin: adminsApi.create,
  toggleAdmin: adminsApi.toggle,
  pushAdminPasswordReset: adminsApi.pushPasswordReset,
  changeAdminRole: adminsApi.changeRole,

  // ----- Notification Center + Bulk SMS (./broadcasts) -----
  broadcastNotification: broadcastsApi.notify,
  listBroadcasts: broadcastsApi.list,
  sendBulkSms: broadcastsApi.sendBulkSms,
  listBulkSms: broadcastsApi.listBulkSms,

  // ----- Credit Rules engine (./creditRules) -----
  listCreditRules: creditRulesApi.list,
  createCreditRule: creditRulesApi.create,
  patchCreditRule: creditRulesApi.patch,
  deleteCreditRule: creditRulesApi.delete,

  // ----- Module registry, roles, capabilities (./access) -----
  myModules: accessApi.myModules,
  accessRegistry: accessApi.registry,
  listRoles: accessApi.listRoles,
  rolesLookup: accessApi.rolesLookup,
  createRole: accessApi.createRole,
  updateRole: accessApi.updateRole,
  deleteRole: accessApi.deleteRole,
  listCapabilities: accessApi.listCapabilities,
  setCapability: accessApi.setCapability,

  // ----- Payment gateway catalog (./gateways) -----
  gatewayCatalog: gatewaysApi.catalog,
  gatewayState: gatewaysApi.state,
  saveGatewayCredentials: gatewaysApi.saveCredentials,
  activateGateway: gatewaysApi.activate,

  // ----- Customer-service contact-us inbox (./contactMessages) -----
  listContactMessages: contactMessagesApi.list,
  getContactMessage: contactMessagesApi.get,
  patchContactMessage: contactMessagesApi.patch,
  addContactNote: contactMessagesApi.addNote,

  // ----- User management + per-user actions (./users) -----
  listUsers: usersApi.list,
  getUser: usersApi.get,
  blockUser: usersApi.block,
  pushUserOtp: usersApi.pushOtp,
  getUserCredits: usersApi.getCredits,
  grantUserCredit: usersApi.grantCredit,
  revokeUserCredit: usersApi.revokeCredit,
  setLeadDiscount: usersApi.setLeadDiscount,

  // ----- Squad management (./groups) -----
  listGroups: groupsApi.list,
  getGroup: groupsApi.get,
  blockGroup: groupsApi.block,
  reassignGroupLead: groupsApi.reassignLead,
  setGroupDiscount: groupsApi.setDiscount,
  clearGroupDiscount: groupsApi.clearDiscount,
  disableGroupCard: groupsApi.disableCard,

  // ----- Third-party integrations (./integrations) -----
  getIntegrations: integrationsApi.get,
  setStripe: integrationsApi.setStripe,
  setTwilio: integrationsApi.setTwilio,
  setSignalWire: integrationsApi.setSignalWire,
  testSignalWire: integrationsApi.testSignalWire,
  setSmsRouting: integrationsApi.setSmsRouting,
  setSmsMode: integrationsApi.setSmsMode,
  testTwilio: integrationsApi.testTwilio,
  setReminders: integrationsApi.setReminders,
  runRemindersNow: integrationsApi.runRemindersNow,
  getIssuingSettings: integrationsApi.getIssuing,
  setIssuingSettings: integrationsApi.setIssuing,

  // ----- PSP reconciliation (./reconciliation) -----
  getReconciliationSettings: reconciliationApi.getSettings,
  setReconciliationSettings: reconciliationApi.setSettings,
  listReconciliations: reconciliationApi.list,
  getReconciliation: reconciliationApi.get,
  manualReconcile: reconciliationApi.manual,
  getMasterAccount: reconciliationApi.getMasterAccount,

  // ----- KMS / Security (./security) -----
  getKmsStatus: kmsApi.getStatus,
  reloadKms: kmsApi.reload,
  rotateKms: kmsApi.rotate,

  // ----- Analytics (./analytics) -----
  getAnalytics: analyticsApi.get,

  // ----- Legal pages (./legal) -----
  listLegalPages: legalApi.list,
  updateLegalPage: legalApi.update,
  uploadLegalMedia: legalApi.uploadMedia,

  // ----- Feature toggles (./features) -----
  getFeatures: featuresApi.get,
  setFeatures: featuresApi.set,

  // ----- Referral program (./referrals) -----
  getReferralSettings: referralsApi.getSettings,
  setReferralSettings: referralsApi.setSettings,
  listReferrers: referralsApi.list,
  getReferrerDetail: referralsApi.getDetail,

  // ----- App config + extra platform fees (./appConfig) -----
  getPlatformFees: appConfigApi.getPlatformFees,
  updatePlatformFees: appConfigApi.updatePlatformFees,
  getAppConfig: appConfigApi.get,
  updateAppConfig: appConfigApi.update,

  // ----- Income & Fees ledger (./incomeFees) -----
  getIncomeFees: incomeFeesApi.get,

  // ----- Master Virtual Card (./masterCard) -----
  getMasterCard: masterCardApi.get,
  issueMasterCard: masterCardApi.issue,
};

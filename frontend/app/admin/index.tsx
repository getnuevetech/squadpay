import { Redirect } from 'expo-router';
// Always bounce to dashboard; the layout will redirect to /admin/login if not authed.
export default function AdminIndex() { return <Redirect href="/admin/login" />; }

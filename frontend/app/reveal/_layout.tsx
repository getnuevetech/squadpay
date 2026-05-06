import { Stack } from 'expo-router';

export default function RevealLayout() {
  return (
    <Stack screenOptions={{ headerShown: false, animation: 'fade' }} />
  );
}

import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { COLORS } from '../src/theme';

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: COLORS.bg },
          headerShadowVisible: false,
          headerTitleStyle: { fontWeight: '700', color: COLORS.text },
          headerTintColor: COLORS.text,
          contentStyle: { backgroundColor: COLORS.bg },
        }}
      >
        <Stack.Screen name="index" options={{ title: 'Home', headerShown: false }} />
        <Stack.Screen name="auth" options={{ title: 'Sign in' }} />
        <Stack.Screen name="create" options={{ title: 'Start a Bill' }} />
        <Stack.Screen name="group/[id]/index" options={{ title: 'Group' }} />
        <Stack.Screen name="group/[id]/items" options={{ title: 'Assign Items' }} />
        <Stack.Screen name="group/[id]/summary" options={{ title: 'Your Share' }} />
        <Stack.Screen name="group/[id]/pay" options={{ title: 'Pay', presentation: 'modal' }} />
        <Stack.Screen name="group/[id]/success" options={{ headerShown: false }} />
        <Stack.Screen name="group/[id]/dashboard" options={{ title: 'Lead Dashboard' }} />
        <Stack.Screen name="join/[code]" options={{ title: 'Join Bill' }} />
      </Stack>
    </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

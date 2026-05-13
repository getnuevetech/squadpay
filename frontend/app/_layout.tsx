import { Stack, useRouter } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { TouchableOpacity, StyleSheet, View } from 'react-native';
import { Home } from 'lucide-react-native';
import { COLORS } from '../src/theme';
import { ToastHost } from '../src/components/Toast';
import { SessionGuard } from '../src/components/SessionGuard';
import { StripeNativeProvider } from '../src/components/StripeNativeProvider';

function HeaderHomeButton() {
  const router = useRouter();
  return (
    <TouchableOpacity
      testID="header-home-btn"
      onPress={() => router.replace('/')}
      activeOpacity={0.85}
      hitSlop={8}
      style={styles.btn}
    >
      <Home size={20} color={COLORS.text} />
    </TouchableOpacity>
  );
}

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
      <StripeNativeProvider>
      <StatusBar style="dark" />
      <View style={{ flex: 1, backgroundColor: COLORS.bg }}>
        <Stack
          screenOptions={{
            headerStyle: { backgroundColor: COLORS.bg },
            headerShadowVisible: false,
            headerTitleStyle: { fontWeight: '700', color: COLORS.text },
            headerTintColor: COLORS.text,
            contentStyle: { backgroundColor: COLORS.bg },
            headerRight: () => <HeaderHomeButton />,
            headerBackTitle: '',
            headerBackButtonDisplayMode: 'minimal',
          }}
        >
          <Stack.Screen name="index" options={{ title: 'Home', headerShown: false }} />
          <Stack.Screen name="auth" options={{ title: 'Sign in', headerShown: false }} />
          <Stack.Screen name="admin" options={{ headerShown: false }} />
          <Stack.Screen name="activity" options={{ headerShown: false }} />
          <Stack.Screen name="squad" options={{ headerShown: false }} />
          <Stack.Screen name="settings" options={{ headerShown: false }} />
          <Stack.Screen name="create" options={{ title: 'Start a Bill' }} />
          <Stack.Screen name="group/[id]/index" options={{ title: 'Squad' }} />
          <Stack.Screen name="group/[id]/items" options={{ title: 'Assign Items' }} />
          <Stack.Screen name="group/[id]/summary" options={{ title: 'Squad Dashboard' }} />
          <Stack.Screen name="group/[id]/pay" options={{ title: 'Pay', presentation: 'modal' }} />
          <Stack.Screen name="group/[id]/success" options={{ headerShown: false }} />
          <Stack.Screen name="group/[id]/dashboard" options={{ title: 'Lead Dashboard' }} />
          <Stack.Screen name="group/[id]/card" options={{ headerShown: false }} />
          <Stack.Screen name="join/[code]" options={{ title: 'Join Bill' }} />
          {/* Inbox uses its own custom header — hide the auto stack header. */}
          <Stack.Screen name="notifications" options={{ headerShown: false }} />
          {/* Custom-headered screens — hide the auto stack header. */}
          <Stack.Screen name="credits" options={{ headerShown: false }} />
          <Stack.Screen name="legal/terms" options={{ headerShown: false }} />
          <Stack.Screen name="contact" options={{ headerShown: false }} />
        </Stack>
        <ToastHost />
        <SessionGuard />
      </View>
      </StripeNativeProvider>
    </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  btn: { paddingHorizontal: 12, paddingVertical: 6 },
});

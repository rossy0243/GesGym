import 'dart:async';

import 'package:cookie_jar/cookie_jar.dart';
import 'package:dio/dio.dart';
import 'package:dio_cookie_manager/dio_cookie_manager.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:path_provider/path_provider.dart';
import 'package:qr_flutter/qr_flutter.dart';

typedef JsonMap = Map<String, dynamic>;

const apiBaseUrl = String.fromEnvironment(
  'GESGYM_API_BASE_URL',
  defaultValue: 'http://10.0.2.2:8010',
);

final memberApiProvider = Provider<MemberApi>((ref) {
  throw UnimplementedError('MemberApi must be overridden at startup.');
});

final sessionProvider =
    StateNotifierProvider<SessionController, AsyncValue<JsonMap?>>((ref) {
      return SessionController(ref.watch(memberApiProvider))..restore();
    });

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final api = await MemberApi.create(apiBaseUrl);
  runApp(
    ProviderScope(
      overrides: [memberApiProvider.overrideWithValue(api)],
      child: const SmartClubMemberApp(),
    ),
  );
}

class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class MemberApi {
  MemberApi._(this._dio);

  final Dio _dio;

  static Future<MemberApi> create(String rawBaseUrl) async {
    final baseUrl = rawBaseUrl.replaceFirst(RegExp(r'/+$'), '');
    final directory = await getApplicationSupportDirectory();
    final cookieJar = PersistCookieJar(
      storage: FileStorage('${directory.path}/smartclub_member_cookies'),
    );
    final dio = Dio(
      BaseOptions(
        baseUrl: baseUrl,
        connectTimeout: const Duration(seconds: 12),
        receiveTimeout: const Duration(seconds: 20),
        contentType: Headers.jsonContentType,
        responseType: ResponseType.json,
        followRedirects: false,
        validateStatus: (_) => true,
      ),
    );
    dio.interceptors.add(CookieManager(cookieJar));
    return MemberApi._(dio);
  }

  Future<JsonMap> login(String username, String password) async {
    final response = await _dio.post<JsonMap>(
      '/members/api/login/',
      data: {'username': username, 'password': password},
    );
    return _unwrapData(response);
  }

  Future<void> logout() async {
    await _dio.post<JsonMap>('/members/api/logout/');
  }

  Future<JsonMap> me() async {
    final response = await _dio.get<JsonMap>('/members/api/me/');
    return _unwrapData(response);
  }

  Future<JsonMap> changePassword({
    required String oldPassword,
    required String newPassword,
    required String confirmPassword,
  }) async {
    final response = await _dio.post<JsonMap>(
      '/members/api/me/password/',
      data: {
        'old_password': oldPassword,
        'new_password1': newPassword,
        'new_password2': confirmPassword,
      },
    );
    return _unwrapData(response);
  }

  Future<JsonMap> markNotificationRead(int id) async {
    final response = await _dio.post<JsonMap>(
      '/members/api/me/notifications/$id/read/',
      data: const {},
    );
    return _unwrapData(response);
  }

  Future<JsonMap> requestPlan(int planId) async {
    final response = await _dio.post<JsonMap>(
      '/members/api/me/subscription-requests/',
      data: {'plan_id': planId},
    );
    return _unwrapData(response);
  }

  Future<JsonMap> createGoal(JsonMap data) async {
    final response = await _dio.post<JsonMap>(
      '/members/api/me/goals/',
      data: data,
    );
    return _unwrapData(response);
  }

  Future<JsonMap> addMeasurement(JsonMap data) async {
    final response = await _dio.post<JsonMap>(
      '/members/api/me/goals/measurements/',
      data: data,
    );
    return _unwrapData(response);
  }

  Future<JsonMap> chooseCoach(int coachId) async {
    final response = await _dio.post<JsonMap>(
      '/members/api/me/coaches/choose/',
      data: {'coach_id': coachId},
    );
    return _unwrapData(response);
  }

  Future<JsonMap> chooseGroupProgram(int programId) async {
    final response = await _dio.post<JsonMap>(
      '/members/api/me/group-programs/choose/',
      data: {'program_id': programId},
    );
    return _unwrapData(response);
  }

  Future<JsonMap> submitFeedback(JsonMap data) async {
    final response = await _dio.post<JsonMap>(
      '/members/api/me/coaching-feedback/',
      data: data,
    );
    return _unwrapData(response);
  }

  JsonMap _unwrapData(Response<JsonMap> response) {
    final body = response.data ?? <String, dynamic>{};
    final ok = body['ok'] == true;
    if (response.statusCode != null &&
        response.statusCode! >= 200 &&
        response.statusCode! < 300 &&
        ok) {
      return Map<String, dynamic>.from(body['data'] as Map? ?? {});
    }
    throw ApiException(
      (body['error'] ?? 'Erreur API SmartClub').toString(),
      statusCode: response.statusCode,
    );
  }
}

class SessionController extends StateNotifier<AsyncValue<JsonMap?>> {
  SessionController(this._api) : super(const AsyncValue.loading());

  final MemberApi _api;

  Future<void> restore() async {
    try {
      state = AsyncValue.data(await _api.me());
    } on ApiException catch (error, stackTrace) {
      if (error.statusCode == 401 || error.statusCode == 403) {
        state = const AsyncValue.data(null);
        return;
      }
      state = AsyncValue.error(error, stackTrace);
    } catch (error, stackTrace) {
      state = AsyncValue.error(error, stackTrace);
    }
  }

  Future<String?> login(String username, String password) async {
    state = const AsyncValue.loading();
    try {
      state = AsyncValue.data(await _api.login(username, password));
      return null;
    } catch (error, stackTrace) {
      state = const AsyncValue.data(null);
      return _message(error, stackTrace);
    }
  }

  Future<void> logout() async {
    await _api.logout();
    state = const AsyncValue.data(null);
  }

  Future<String?> runAction(Future<JsonMap> Function(MemberApi api) action) async {
    try {
      state = AsyncValue.data(await action(_api));
      return null;
    } catch (error, stackTrace) {
      return _message(error, stackTrace);
    }
  }

  String _message(Object error, StackTrace stackTrace) {
    if (error is ApiException) return error.message;
    return 'Action impossible pour le moment.';
  }
}

class SmartClubMemberApp extends ConsumerWidget {
  const SmartClubMemberApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final session = ref.watch(sessionProvider);
    return MaterialApp(
      title: 'SmartClub Membre',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFFF6F7F2),
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF102820),
          primary: const Color(0xFF102820),
          secondary: const Color(0xFF2F6BFF),
          tertiary: const Color(0xFFE0A11A),
          surface: Colors.white,
        ),
        cardTheme: CardThemeData(
          color: Colors.white,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(8),
            side: BorderSide(color: Colors.black.withValues(alpha: 0.07)),
          ),
        ),
        inputDecorationTheme: InputDecorationTheme(
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
          filled: true,
          fillColor: Colors.white,
        ),
      ),
      home: session.when(
        loading: () => const SplashScreen(),
        error: (error, _) => FatalErrorScreen(message: error.toString()),
        data: (data) => data == null
            ? const LoginScreen()
            : DashboardScreen(data: data),
      ),
    );
  }
}

class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(child: CircularProgressIndicator()),
    );
  }
}

class FatalErrorScreen extends ConsumerWidget {
  const FatalErrorScreen({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.wifi_off_rounded, size: 42),
                const SizedBox(height: 12),
                Text(message, textAlign: TextAlign.center),
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: () => ref.read(sessionProvider.notifier).restore(),
                  icon: const Icon(Icons.refresh_rounded),
                  label: const Text('Reessayer'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);
    final error = await ref
        .read(sessionProvider.notifier)
        .login(_usernameController.text.trim(), _passwordController.text);
    if (!mounted) return;
    setState(() => _busy = false);
    if (error != null) _showSnack(context, error);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 32, 20, 20),
          children: [
            const Text(
              'SmartClub Membre',
              style: TextStyle(fontSize: 30, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 8),
            Text(
              'Connexion membre GesGym',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 28),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(18),
                child: Form(
                  key: _formKey,
                  child: Column(
                    children: [
                      TextFormField(
                        controller: _usernameController,
                        textInputAction: TextInputAction.next,
                        decoration: const InputDecoration(
                          labelText: 'Identifiant',
                          prefixIcon: Icon(Icons.person_outline_rounded),
                        ),
                        validator: (value) => (value == null || value.trim().isEmpty)
                            ? 'Identifiant requis'
                            : null,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        controller: _passwordController,
                        obscureText: true,
                        onFieldSubmitted: (_) => _submit(),
                        decoration: const InputDecoration(
                          labelText: 'Mot de passe',
                          prefixIcon: Icon(Icons.lock_outline_rounded),
                        ),
                        validator: (value) => (value == null || value.isEmpty)
                            ? 'Mot de passe requis'
                            : null,
                      ),
                      const SizedBox(height: 18),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton.icon(
                          onPressed: _busy ? null : _submit,
                          icon: _busy
                              ? const SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(strokeWidth: 2),
                                )
                              : const Icon(Icons.login_rounded),
                          label: const Text('Se connecter'),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            const SizedBox(height: 18),
            Text(
              'API: $apiBaseUrl',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}

class DashboardScreen extends ConsumerStatefulWidget {
  const DashboardScreen({super.key, required this.data});

  final JsonMap data;

  @override
  ConsumerState<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends ConsumerState<DashboardScreen> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final data = ref.watch(sessionProvider).value ?? widget.data;
    final member = mapOf(data, 'member');
    final gym = mapOf(data, 'gym');
    final pages = [
      HomePage(data: data),
      MessagesPage(data: data),
      SubscriptionPage(data: data),
      PlansPage(data: data),
      GoalPage(data: data),
      SecurityPage(data: data),
    ];
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              textOf(member, 'full_name', fallback: 'Membre'),
              style: const TextStyle(fontWeight: FontWeight.w800),
            ),
            Text(
              textOf(gym, 'name', fallback: 'SmartClub'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Actualiser',
            onPressed: () => ref.read(sessionProvider.notifier).restore(),
            icon: const Icon(Icons.refresh_rounded),
          ),
          IconButton(
            tooltip: 'Deconnexion',
            onPressed: () => ref.read(sessionProvider.notifier).logout(),
            icon: const Icon(Icons.logout_rounded),
          ),
        ],
      ),
      body: SafeArea(child: pages[_index]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (value) => setState(() => _index = value),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.qr_code_2_rounded), label: 'Carte'),
          NavigationDestination(icon: Icon(Icons.mail_outline_rounded), label: 'Messages'),
          NavigationDestination(icon: Icon(Icons.credit_card_rounded), label: 'Abonnement'),
          NavigationDestination(icon: Icon(Icons.workspace_premium_rounded), label: 'Formules'),
          NavigationDestination(icon: Icon(Icons.track_changes_rounded), label: 'Objectif'),
          NavigationDestination(icon: Icon(Icons.lock_outline_rounded), label: 'Securite'),
        ],
      ),
    );
  }
}

class HomePage extends ConsumerWidget {
  const HomePage({super.key, required this.data});

  final JsonMap data;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final member = mapOf(data, 'member');
    final subscription = nullableMapOf(data, 'subscription');
    final coaching = mapOf(data, 'coaching');
    final rights = mapOf(data, 'coaching_rights');
    final access = mapOf(data, 'access');
    final messages = mapOf(data, 'messages');
    final currentCoaches = listOf(coaching, 'current_coaches');
    final availableCoaches = listOf(coaching, 'available_coaches');
    final selectedPrograms = listOf(coaching, 'selected_group_programs');
    final availablePrograms = listOf(coaching, 'available_group_programs');

    return RefreshIndicator(
      onRefresh: () => ref.read(sessionProvider.notifier).restore(),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            StatusPill(label: textOf(member, 'status_label')),
                            const SizedBox(height: 10),
                            Text(
                              textOf(member, 'full_name'),
                              style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            Text(textOf(member, 'code')),
                          ],
                        ),
                      ),
                      SizedBox(
                        width: 124,
                        child: QrImageView(
                          data: textOf(member, 'qr_data'),
                          size: 118,
                          backgroundColor: Colors.white,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  Row(
                    children: [
                      Expanded(
                        child: StatTile(
                          label: 'Restant',
                          value: daysLabel(member['days_remaining']),
                          icon: Icons.event_available_rounded,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: StatTile(
                          label: 'Messages',
                          value: '${messages['unread_count'] ?? 0}',
                          icon: Icons.mail_outline_rounded,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: StatTile(
                          label: 'Acces',
                          value: '${access['granted_count'] ?? 0}',
                          icon: Icons.door_front_door_outlined,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          Section(
            title: 'Abonnement',
            action: subscription == null ? null : '${subscription['progress'] ?? 0}%',
            child: subscription == null
                ? const EmptyState('Aucun abonnement actif.')
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        textOf(mapOf(subscription, 'plan'), 'name'),
                        style: Theme.of(context).textTheme.titleLarge?.copyWith(
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 8),
                      LinearProgressIndicator(
                        value: ((subscription['progress'] ?? 0) as num).toDouble() / 100,
                        minHeight: 8,
                        borderRadius: BorderRadius.circular(6),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        '${dateShort(subscription['start_date'])} - ${dateShort(subscription['end_date'])}',
                      ),
                    ],
                  ),
          ),
          Section(
            title: 'Coaching',
            action: textOf(rights, 'level_label', fallback: ''),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(textOf(rights, 'mode_label', fallback: 'Aucun coaching')),
                const SizedBox(height: 12),
                if (currentCoaches.isEmpty && selectedPrograms.isEmpty)
                  const EmptyState('Aucun coach ou programme rattache.')
                else ...[
                  for (final coach in currentCoaches)
                    CompactRow(
                      icon: Icons.fitness_center_rounded,
                      title: textOf(coach, 'name'),
                      subtitle: textOf(coach, 'specialty'),
                      trailing: TextButton(
                        onPressed: () => showFeedbackSheet(
                          context,
                          ref,
                          kind: 'coach',
                          coachId: intOf(coach, 'id'),
                        ),
                        child: const Text('Avis'),
                      ),
                    ),
                  for (final program in selectedPrograms)
                    CompactRow(
                      icon: Icons.groups_rounded,
                      title: textOf(program, 'name'),
                      subtitle: 'Coach ${textOf(mapOf(program, 'coach'), 'name')}',
                      trailing: TextButton(
                        onPressed: () => showFeedbackSheet(
                          context,
                          ref,
                          kind: 'group_program',
                          coachId: intOf(mapOf(program, 'coach'), 'id'),
                          programId: intOf(program, 'id'),
                        ),
                        child: const Text('Avis'),
                      ),
                    ),
                ],
                if (availableCoaches.isNotEmpty) ...[
                  const Divider(height: 24),
                  const Text('Choisir mon coach', style: TextStyle(fontWeight: FontWeight.w700)),
                  for (final coach in availableCoaches)
                    CompactRow(
                      icon: Icons.person_search_rounded,
                      title: textOf(coach, 'name'),
                      subtitle: textOf(coach, 'specialty'),
                      trailing: boolOf(coach, 'is_current')
                          ? const Chip(label: Text('Actuel'))
                          : TextButton(
                              onPressed: () => runMemberAction(
                                context,
                                ref,
                                (api) => api.chooseCoach(intOf(coach, 'id')),
                                success: 'Coach mis a jour.',
                              ),
                              child: const Text('Choisir'),
                            ),
                    ),
                ],
                if (availablePrograms.isNotEmpty) ...[
                  const Divider(height: 24),
                  const Text('Programme groupe', style: TextStyle(fontWeight: FontWeight.w700)),
                  for (final program in availablePrograms)
                    CompactRow(
                      icon: Icons.group_add_rounded,
                      title: textOf(program, 'name'),
                      subtitle: '${program['participants_total']}/${program['capacity']} participants',
                      trailing: boolOf(program, 'is_current')
                          ? const Chip(label: Text('Actuel'))
                          : TextButton(
                              onPressed: boolOf(program, 'is_full')
                                  ? null
                                  : () => runMemberAction(
                                      context,
                                      ref,
                                      (api) => api.chooseGroupProgram(intOf(program, 'id')),
                                      success: 'Programme mis a jour.',
                                    ),
                              child: Text(boolOf(program, 'is_full') ? 'Complet' : 'Rejoindre'),
                            ),
                    ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class MessagesPage extends ConsumerWidget {
  const MessagesPage({super.key, required this.data});

  final JsonMap data;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final messages = mapOf(data, 'messages');
    final items = listOf(messages, 'items');
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
      children: [
        Section(
          title: 'Boite de reception',
          action: '${messages['unread_count'] ?? 0} non lus',
          child: items.isEmpty
              ? const EmptyState('Aucun message pour le moment.')
              : Column(
                  children: [
                    for (final item in items)
                      CompactRow(
                        icon: boolOf(item, 'is_read')
                            ? Icons.mark_email_read_outlined
                            : Icons.markunread_rounded,
                        title: textOf(item, 'title'),
                        subtitle: '${dateTimeShort(item['created_at'])}\n${textOf(item, 'message')}',
                        trailing: boolOf(item, 'is_read')
                            ? null
                            : TextButton(
                                onPressed: () => runMemberAction(
                                  context,
                                  ref,
                                  (api) => api.markNotificationRead(intOf(item, 'id')),
                                  success: 'Message marque comme lu.',
                                ),
                                child: const Text('Lu'),
                              ),
                      ),
                  ],
                ),
        ),
      ],
    );
  }
}

class SubscriptionPage extends StatelessWidget {
  const SubscriptionPage({super.key, required this.data});

  final JsonMap data;

  @override
  Widget build(BuildContext context) {
    final subscription = nullableMapOf(data, 'subscription');
    final payments = listOf(data, 'payments');
    final access = mapOf(data, 'access');
    final logs = listOf(access, 'logs');
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
      children: [
        Section(
          title: 'Abonnement actif',
          child: subscription == null
              ? const EmptyState('Aucun abonnement actif.')
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      textOf(mapOf(subscription, 'plan'), 'name'),
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 10),
                    DetailGrid(
                      items: {
                        'Debut': dateShort(subscription['start_date']),
                        'Expiration': dateShort(subscription['end_date']),
                        'Prix': '${money(mapOf(subscription, 'plan')['price'])} USD',
                        'Progression': '${subscription['progress'] ?? 0}%',
                      },
                    ),
                  ],
                ),
        ),
        Section(
          title: 'Paiements',
          child: payments.isEmpty
              ? const EmptyState('Aucun paiement recent.')
              : Column(
                  children: [
                    for (final payment in payments)
                      CompactRow(
                        icon: Icons.payments_outlined,
                        title: textOf(payment, 'description'),
                        subtitle: '${dateTimeShort(payment['created_at'])} - ${textOf(payment, 'method_label')}',
                        trailing: Text('${money(payment['amount_cdf'])} CDF'),
                      ),
                  ],
                ),
        ),
        Section(
          title: 'Acces recents',
          action: '${access['denied_count'] ?? 0} refuses',
          child: logs.isEmpty
              ? const EmptyState('Aucun acces enregistre.')
              : Column(
                  children: [
                    for (final log in logs)
                      CompactRow(
                        icon: boolOf(log, 'access_granted')
                            ? Icons.check_circle_outline_rounded
                            : Icons.cancel_outlined,
                        title: textOf(log, 'status_label'),
                        subtitle: boolOf(log, 'access_granted')
                            ? dateTimeShort(log['check_in_time'])
                            : '${dateTimeShort(log['check_in_time'])}\n${textOf(log, 'denial_reason')}',
                      ),
                  ],
                ),
        ),
      ],
    );
  }
}

class PlansPage extends ConsumerWidget {
  const PlansPage({super.key, required this.data});

  final JsonMap data;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final plans = mapOf(data, 'plans');
    final items = listOf(plans, 'items');
    final pending = listOf(plans, 'pending_requests');
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
      children: [
        if (pending.isNotEmpty)
          Section(
            title: 'Demande en attente',
            child: Column(
              children: [
                for (final request in pending)
                  CompactRow(
                    icon: Icons.hourglass_top_rounded,
                    title: textOf(request, 'plan_name'),
                    subtitle: '${money(request['price_usd'])} USD - ${textOf(request, 'status_label')}',
                  ),
              ],
            ),
          ),
        Section(
          title: 'Formules',
          child: items.isEmpty
              ? const EmptyState('Aucune formule active.')
              : Column(
                  children: [
                    for (final plan in items)
                      PlanCard(
                        plan: plan,
                        onRequest: boolOf(plan, 'is_current') || boolOf(plan, 'is_pending')
                            ? null
                            : () => runMemberAction(
                                context,
                                ref,
                                (api) => api.requestPlan(intOf(plan, 'id')),
                                success: 'Demande de souscription envoyee.',
                              ),
                      ),
                  ],
                ),
        ),
      ],
    );
  }
}

class GoalPage extends ConsumerWidget {
  const GoalPage({super.key, required this.data});

  final JsonMap data;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final goal = nullableMapOf(data, 'goal');
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
      children: [
        Section(
          title: 'Objectif poids',
          child: goal == null
              ? Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const EmptyState('Aucun objectif actif.'),
                    const SizedBox(height: 12),
                    FilledButton.icon(
                      onPressed: () => showGoalSheet(context, ref),
                      icon: const Icon(Icons.add_rounded),
                      label: const Text('Creer mon objectif'),
                    ),
                  ],
                )
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    DetailGrid(
                      items: {
                        'Objectif': textOf(goal, 'goal_type_label'),
                        'Cible': '${money(goal['target_weight'])} kg',
                        'Progression': '${goal['progress_percent'] ?? 0}%',
                        'Reste': goal['remaining_weight'] == null
                            ? 'En attente'
                            : '${money(goal['remaining_weight'])} kg',
                      },
                    ),
                    const SizedBox(height: 12),
                    LinearProgressIndicator(
                      value: ((goal['progress_percent'] ?? 0) as num).toDouble() / 100,
                      minHeight: 8,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    if (boolOf(goal, 'can_member_record')) ...[
                      const SizedBox(height: 14),
                      FilledButton.icon(
                        onPressed: () => showMeasurementSheet(context, ref),
                        icon: const Icon(Icons.monitor_weight_outlined),
                        label: const Text('Ajouter une pesee'),
                      ),
                    ] else if (textOf(goal, 'waiting_for') == 'coach') ...[
                      const SizedBox(height: 14),
                      const EmptyState('Le coach doit lancer la premiere pesee.'),
                    ],
                    const Divider(height: 28),
                    Text(
                      'Dernieres pesees',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 8),
                    for (final measurement in listOf(goal, 'measurements'))
                      CompactRow(
                        icon: Icons.monitor_weight_outlined,
                        title: '${money(measurement['weight'])} kg',
                        subtitle: '${dateShort(measurement['measured_at'])} - ${textOf(measurement, 'source_label')}',
                      ),
                    if (listOf(goal, 'measurements').isEmpty)
                      const EmptyState('Aucune pesee enregistree.'),
                  ],
                ),
        ),
      ],
    );
  }
}

class SecurityPage extends ConsumerStatefulWidget {
  const SecurityPage({super.key, required this.data});

  final JsonMap data;

  @override
  ConsumerState<SecurityPage> createState() => _SecurityPageState();
}

class _SecurityPageState extends ConsumerState<SecurityPage> {
  final _formKey = GlobalKey<FormState>();
  final _oldPassword = TextEditingController();
  final _newPassword = TextEditingController();
  final _confirmPassword = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _oldPassword.dispose();
    _newPassword.dispose();
    _confirmPassword.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _busy = true);
    final error = await ref.read(sessionProvider.notifier).runAction(
          (api) => api.changePassword(
            oldPassword: _oldPassword.text,
            newPassword: _newPassword.text,
            confirmPassword: _confirmPassword.text,
          ),
        );
    if (!mounted) return;
    setState(() => _busy = false);
    if (error != null) {
      _showSnack(context, error);
      return;
    }
    _oldPassword.clear();
    _newPassword.clear();
    _confirmPassword.clear();
    _showSnack(context, 'Mot de passe mis a jour.');
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
      children: [
        Section(
          title: 'Mot de passe',
          child: Form(
            key: _formKey,
            child: Column(
              children: [
                PasswordField(controller: _oldPassword, label: 'Mot de passe actuel'),
                const SizedBox(height: 12),
                PasswordField(controller: _newPassword, label: 'Nouveau mot de passe'),
                const SizedBox(height: 12),
                PasswordField(controller: _confirmPassword, label: 'Confirmation'),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: _busy ? null : _submit,
                    icon: const Icon(Icons.save_rounded),
                    label: const Text('Mettre a jour'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class PasswordField extends StatelessWidget {
  const PasswordField({super.key, required this.controller, required this.label});

  final TextEditingController controller;
  final String label;

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: controller,
      obscureText: true,
      decoration: InputDecoration(labelText: label),
      validator: (value) {
        if (value == null || value.isEmpty) return 'Champ requis';
        if (label != 'Mot de passe actuel' && value.length < 8) {
          return '8 caracteres minimum';
        }
        return null;
      },
    );
  }
}

class Section extends StatelessWidget {
  const Section({super.key, required this.title, required this.child, this.action});

  final String title;
  final String? action;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    title,
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
                if (action != null)
                  Chip(
                    visualDensity: VisualDensity.compact,
                    label: Text(action!),
                  ),
              ],
            ),
            const SizedBox(height: 12),
            child,
          ],
        ),
      ),
    );
  }
}

class StatTile extends StatelessWidget {
  const StatTile({super.key, required this.label, required this.value, required this.icon});

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFFF0F3EF),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20),
          const SizedBox(height: 8),
          Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
          Text(label, style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }
}

class StatusPill extends StatelessWidget {
  const StatusPill({super.key, required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: const Color(0xFFE8F4EC),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        child: Text(
          label,
          style: const TextStyle(fontWeight: FontWeight.w700, color: Color(0xFF17643A)),
        ),
      ),
    );
  }
}

class CompactRow extends StatelessWidget {
  const CompactRow({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle = '',
    this.trailing,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          CircleAvatar(
            radius: 18,
            backgroundColor: const Color(0xFFE9EEF8),
            foregroundColor: const Color(0xFF2F55A4),
            child: Icon(icon, size: 20),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontWeight: FontWeight.w800)),
                if (subtitle.isNotEmpty)
                  Text(
                    subtitle,
                    style: Theme.of(context).textTheme.bodySmall,
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                  ),
              ],
            ),
          ),
          if (trailing != null) ...[
            const SizedBox(width: 8),
            trailing!,
          ],
        ],
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFF0F1ED),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(message, style: Theme.of(context).textTheme.bodyMedium),
    );
  }
}

class DetailGrid extends StatelessWidget {
  const DetailGrid({super.key, required this.items});

  final Map<String, String> items;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final item in items.entries)
          SizedBox(
            width: (MediaQuery.sizeOf(context).width - 58) / 2,
            child: Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFFF4F6F3),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(item.key, style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 4),
                  Text(item.value, style: const TextStyle(fontWeight: FontWeight.w800)),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

class PlanCard extends StatelessWidget {
  const PlanCard({super.key, required this.plan, this.onRequest});

  final JsonMap plan;
  final VoidCallback? onRequest;

  @override
  Widget build(BuildContext context) {
    final offers = listOf(plan, 'offers');
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: boolOf(plan, 'is_featured') ? const Color(0xFFFFF7DF) : const Color(0xFFF7F8F5),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: boolOf(plan, 'is_current') ? const Color(0xFF17643A) : Colors.black.withValues(alpha: 0.06),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  textOf(plan, 'name'),
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
              if (boolOf(plan, 'is_featured')) const Chip(label: Text('Populaire')),
              if (boolOf(plan, 'is_current')) const Chip(label: Text('Actuel')),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '${money(plan['price'])} USD - ${plan['duration_days']} jours',
            style: const TextStyle(fontWeight: FontWeight.w800),
          ),
          if (textOf(plan, 'description').isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(textOf(plan, 'description')),
          ],
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final offer in offers)
                Chip(
                  visualDensity: VisualDensity.compact,
                  label: Text(textOf(offer, 'name')),
                ),
              if (offers.isEmpty)
                const Chip(
                  visualDensity: VisualDensity.compact,
                  label: Text('Acces standard'),
                ),
            ],
          ),
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: onRequest,
              icon: Icon(
                boolOf(plan, 'is_pending') ? Icons.hourglass_top_rounded : Icons.send_rounded,
              ),
              label: Text(
                boolOf(plan, 'is_current')
                    ? 'Formule active'
                    : boolOf(plan, 'is_pending')
                        ? 'En attente'
                        : 'Demander cette formule',
              ),
            ),
          ),
        ],
      ),
    );
  }
}

Future<void> runMemberAction(
  BuildContext context,
  WidgetRef ref,
  Future<JsonMap> Function(MemberApi api) action, {
  required String success,
}) async {
  final error = await ref.read(sessionProvider.notifier).runAction(action);
  if (!context.mounted) return;
  _showSnack(context, error ?? success);
}

Future<void> showFeedbackSheet(
  BuildContext context,
  WidgetRef ref, {
  required String kind,
  required int coachId,
  int? programId,
}) async {
  final comment = TextEditingController();
  int overall = 5;
  int listening = 5;
  int clarity = 5;
  int motivation = 5;
  int availability = 5;
  bool wantsContact = false;

  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (sheetContext) {
      return StatefulBuilder(
        builder: (context, setSheetState) {
          return Padding(
            padding: EdgeInsets.fromLTRB(
              16,
              16,
              16,
              MediaQuery.viewInsetsOf(context).bottom + 16,
            ),
            child: ListView(
              shrinkWrap: true,
              children: [
                Text(
                  kind == 'group_program' ? 'Avis programme' : 'Avis coach',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 12),
                RatingField(label: 'Satisfaction', value: overall, onChanged: (v) => setSheetState(() => overall = v)),
                RatingField(label: 'Ecoute', value: listening, onChanged: (v) => setSheetState(() => listening = v)),
                RatingField(label: 'Clarte', value: clarity, onChanged: (v) => setSheetState(() => clarity = v)),
                RatingField(label: 'Motivation', value: motivation, onChanged: (v) => setSheetState(() => motivation = v)),
                RatingField(label: 'Disponibilite', value: availability, onChanged: (v) => setSheetState(() => availability = v)),
                TextField(
                  controller: comment,
                  maxLines: 3,
                  decoration: const InputDecoration(labelText: 'Commentaire'),
                ),
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  value: wantsContact,
                  onChanged: (value) => setSheetState(() => wantsContact = value ?? false),
                  title: const Text('Je souhaite etre recontacte'),
                ),
                FilledButton.icon(
                  onPressed: () async {
                    Navigator.pop(sheetContext);
                    await runMemberAction(
                      context,
                      ref,
                      (api) => api.submitFeedback({
                        'feedback_kind': kind,
                        'coach_id': coachId,
                        ...?programId == null ? null : {'program_id': programId},
                        'overall_rating': overall,
                        'listening_rating': listening,
                        'clarity_rating': clarity,
                        'motivation_rating': motivation,
                        'availability_rating': availability,
                        'comment': comment.text.trim(),
                        'wants_contact': wantsContact,
                      }),
                      success: 'Avis envoye.',
                    );
                  },
                  icon: const Icon(Icons.send_rounded),
                  label: const Text('Envoyer'),
                ),
              ],
            ),
          );
        },
      );
    },
  );
}

class RatingField extends StatelessWidget {
  const RatingField({
    super.key,
    required this.label,
    required this.value,
    required this.onChanged,
  });

  final String label;
  final int value;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          Expanded(child: Text(label)),
          DropdownButton<int>(
            value: value,
            items: [
              for (var score = 1; score <= 5; score++)
                DropdownMenuItem(value: score, child: Text('$score/5')),
            ],
            onChanged: (next) => onChanged(next ?? value),
          ),
        ],
      ),
    );
  }
}

Future<void> showGoalSheet(BuildContext context, WidgetRef ref) async {
  final formKey = GlobalKey<FormState>();
  final targetWeight = TextEditingController();
  final targetDate = TextEditingController();
  final note = TextEditingController();
  String goalType = 'lose_weight';
  String starter = 'member';

  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (sheetContext) {
      return StatefulBuilder(
        builder: (context, setSheetState) {
          return Padding(
            padding: EdgeInsets.fromLTRB(
              16,
              16,
              16,
              MediaQuery.viewInsetsOf(context).bottom + 16,
            ),
            child: Form(
              key: formKey,
              child: ListView(
                shrinkWrap: true,
                children: [
                  Text(
                    'Nouvel objectif',
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: goalType,
                    decoration: const InputDecoration(labelText: 'Type'),
                    items: const [
                      DropdownMenuItem(value: 'lose_weight', child: Text('Perte de poids')),
                      DropdownMenuItem(value: 'gain_weight', child: Text('Prise de poids')),
                    ],
                    onChanged: (value) => setSheetState(() => goalType = value ?? goalType),
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: targetWeight,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: 'Poids cible (kg)'),
                    validator: (value) => (double.tryParse(value ?? '') ?? 0) <= 0
                        ? 'Poids requis'
                        : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: targetDate,
                    decoration: const InputDecoration(labelText: 'Date cible YYYY-MM-DD'),
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: starter,
                    decoration: const InputDecoration(labelText: 'Premiere pesee'),
                    items: const [
                      DropdownMenuItem(value: 'member', child: Text('Je commence')),
                      DropdownMenuItem(value: 'coach', child: Text('Le coach commence')),
                    ],
                    onChanged: (value) => setSheetState(() => starter = value ?? starter),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: note,
                    maxLines: 3,
                    decoration: const InputDecoration(labelText: 'Note'),
                  ),
                  const SizedBox(height: 14),
                  FilledButton.icon(
                    onPressed: () async {
                      if (!formKey.currentState!.validate()) return;
                      Navigator.pop(sheetContext);
                      await runMemberAction(
                        context,
                        ref,
                        (api) => api.createGoal({
                          'goal_type': goalType,
                          'target_weight': targetWeight.text,
                          if (targetDate.text.trim().isNotEmpty) 'target_date': targetDate.text.trim(),
                          'measurement_starter': starter,
                          'note': note.text.trim(),
                        }),
                        success: 'Objectif cree.',
                      );
                    },
                    icon: const Icon(Icons.add_rounded),
                    label: const Text('Creer'),
                  ),
                ],
              ),
            ),
          );
        },
      );
    },
  );
}

Future<void> showMeasurementSheet(BuildContext context, WidgetRef ref) async {
  final formKey = GlobalKey<FormState>();
  final weight = TextEditingController();
  final measuredAt = TextEditingController(
    text: DateFormat('yyyy-MM-dd').format(DateTime.now()),
  );
  final note = TextEditingController();

  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (sheetContext) {
      return Padding(
        padding: EdgeInsets.fromLTRB(
          16,
          16,
          16,
          MediaQuery.viewInsetsOf(sheetContext).bottom + 16,
        ),
        child: Form(
          key: formKey,
          child: ListView(
            shrinkWrap: true,
            children: [
              Text(
                'Nouvelle pesee',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: weight,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Poids (kg)'),
                validator: (value) =>
                    (double.tryParse(value ?? '') ?? 0) <= 0 ? 'Poids requis' : null,
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: measuredAt,
                decoration: const InputDecoration(labelText: 'Date YYYY-MM-DD'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: note,
                maxLines: 2,
                decoration: const InputDecoration(labelText: 'Note'),
              ),
              const SizedBox(height: 14),
              FilledButton.icon(
                onPressed: () async {
                  if (!formKey.currentState!.validate()) return;
                  Navigator.pop(sheetContext);
                  await runMemberAction(
                    context,
                    ref,
                    (api) => api.addMeasurement({
                      'weight': weight.text,
                      'measured_at': measuredAt.text.trim(),
                      'note': note.text.trim(),
                    }),
                    success: 'Pesee enregistree.',
                  );
                },
                icon: const Icon(Icons.save_rounded),
                label: const Text('Enregistrer'),
              ),
            ],
          ),
        ),
      );
    },
  );
}

JsonMap mapOf(JsonMap source, String key) {
  final value = source[key];
  if (value is Map) return Map<String, dynamic>.from(value);
  return <String, dynamic>{};
}

JsonMap? nullableMapOf(JsonMap source, String key) {
  final value = source[key];
  if (value is Map) return Map<String, dynamic>.from(value);
  return null;
}

List<JsonMap> listOf(JsonMap source, String key) {
  final value = source[key];
  if (value is List) {
    return value.whereType<Map>().map((item) => Map<String, dynamic>.from(item)).toList();
  }
  return const [];
}

String textOf(JsonMap source, String key, {String fallback = '-'}) {
  final value = source[key];
  if (value == null) return fallback;
  final text = value.toString();
  return text.isEmpty ? fallback : text;
}

int intOf(JsonMap source, String key) {
  final value = source[key];
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse(value?.toString() ?? '') ?? 0;
}

bool boolOf(JsonMap source, String key) => source[key] == true;

String money(Object? value) {
  final number = value is num ? value : num.tryParse(value?.toString() ?? '') ?? 0;
  return NumberFormat.decimalPattern('fr_FR').format(number);
}

String dateShort(Object? value) {
  if (value == null) return '-';
  final parsed = DateTime.tryParse(value.toString());
  if (parsed == null) return value.toString();
  return DateFormat('dd/MM/yyyy', 'fr_FR').format(parsed);
}

String dateTimeShort(Object? value) {
  if (value == null) return '-';
  final parsed = DateTime.tryParse(value.toString());
  if (parsed == null) return value.toString();
  return DateFormat('dd/MM HH:mm', 'fr_FR').format(parsed.toLocal());
}

String daysLabel(Object? value) {
  if (value == null) return '-';
  final days = value is num ? value.toInt() : int.tryParse(value.toString());
  if (days == null) return '-';
  if (days < 0) return 'Expire';
  return '$days j';
}

void _showSnack(BuildContext context, String message) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(message)));
}

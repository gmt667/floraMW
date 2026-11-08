import 'localization.dart';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'models.dart';
import 'preferences.dart';
import 'locale_data.dart';
import 'store.dart';
import 'ui.dart';
import 'screens/profile.dart';
import 'screens/identify.dart';
import 'screens/garden.dart';
import 'screens/settings.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const Bootstrap());
}

class Bootstrap extends StatefulWidget {
  const Bootstrap({super.key});
  @override
  State<Bootstrap> createState() => _BootstrapState();
}

class _BootstrapState extends State<Bootstrap> {
  AppStore? store;
  bool failed = false;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() => failed = false);
    try {
      await TranslationCatalog.load();
      final prefs = await SharedPreferences.getInstance();
      if (mounted) setState(() => store = AppStore(prefs));
    } catch (_) {
      if (mounted) setState(() => failed = true);
    }
  }

  @override
  void dispose() {
    store?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (store != null) return FloraMWApp(store: store!);
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      home: Scaffold(
        backgroundColor: cream,
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Image.asset('assets/icon.png', height: 84),
                const SizedBox(height: 18),
                const FloraText(
                  'FloraMW',
                  style: TextStyle(
                    fontSize: 32,
                    color: forest,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 24),
                if (!failed)
                  const CircularProgressIndicator()
                else ...[
                  const FloraText('Device storage could not be opened.'),
                  TextButton(
                    onPressed: load,
                    child: const FloraText('Try again'),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class FloraMWApp extends StatelessWidget {
  final AppStore store;
  const FloraMWApp({super.key, required this.store});
  ThemeData theme(Brightness brightness) => ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: ColorScheme.fromSeed(
      seedColor: forest,
      brightness: brightness,
    ),
    scaffoldBackgroundColor: brightness == Brightness.light
        ? cream
        : const Color(0xff151e19),
    appBarTheme: AppBarTheme(
      backgroundColor: brightness == Brightness.light
          ? cream
          : const Color(0xff151e19),
    ),
    inputDecorationTheme: InputDecorationTheme(
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 16),
      ),
    ),
  );
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: store,
    builder: (context, _) => MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'FloraMW',
      theme: theme(Brightness.light),
      darkTheme: theme(Brightness.dark),
      themeMode: store.dark ? ThemeMode.dark : ThemeMode.light,
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          textScaler: TextScaler.linear(
            MediaQuery.textScalerOf(context).scale(1) *
                (store.largeText ? 1.2 : 1),
          ),
        ),
        child: FloraScope(store: store, child: child!),
      ),
      home: store.onboarding
          ? HomeScreen(store: store)
          : WelcomeScreen(store: store),
    ),
  );
}

class WelcomeScreen extends StatefulWidget {
  final AppStore store;
  final VoidCallback? onFinished;
  const WelcomeScreen({super.key, required this.store, this.onFinished});
  @override
  State<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends State<WelcomeScreen> {
  int step = 0;
  bool saving = false;
  final controller = PageController();
  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  Future<void> finish() async {
    final accepted = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (_) => SetupScreen(store: widget.store)),
    );
    if (accepted != true || !mounted) return;
    setState(() => saving = true);
    try {
      widget.store.onboarding = true;
      await widget.store.commit();
      widget.onFinished?.call();
    } catch (_) {
      widget.store.onboarding = false;
      if (mounted)
        message(
          context,
          'Could not save introduction preferences. Please retry.',
        );
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    const icons = [
      Icons.local_florist_outlined,
      Icons.camera_alt_outlined,
      Icons.menu_book_outlined,
    ];
    const titles = [
      'Meet FloraMW.',
      'A discovery in your pocket.',
      'Knowledge grows with care.',
    ];
    const bodies = [
      'Explore flowers through a Malawi-focused botanical companion. Save discoveries and build your own field journal.',
      'Take a photo or choose one from your gallery. This frontend uses clearly labelled sample results until real identification is connected.',
      'Scientific evidence and community knowledge are kept separate. Verify identity, sources, safety and harvesting permissions before acting.',
    ];
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.all(20),
              child: Row(
                children: [
                  const Icon(Icons.spa_outlined),
                  const SizedBox(width: 8),
                  const FloraText(
                    'FloraMW',
                    style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
                  ),
                  const Spacer(),
                  TextButton(
                    onPressed: saving ? null : finish,
                    child: const FloraText('Skip'),
                  ),
                ],
              ),
            ),
            Expanded(
              child: PageView.builder(
                controller: controller,
                itemCount: 3,
                onPageChanged: (v) => setState(() => step = v),
                itemBuilder: (context, i) => ListView(
                  padding: const EdgeInsets.all(28),
                  children: [
                    Container(
                      height: 230,
                      decoration: BoxDecoration(
                        color: const Color(0xffe4eadb),
                        borderRadius: BorderRadius.circular(32),
                      ),
                      child: Icon(icons[i], size: 100, color: forest),
                    ),
                    const SizedBox(height: 32),
                    FloraText(
                      titles[i],
                      style: Theme.of(context).textTheme.headlineLarge,
                    ),
                    const SizedBox(height: 20),
                    FloraText(
                      bodies[i],
                      style: const TextStyle(fontSize: 17, height: 1.7),
                    ),
                  ],
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: List.generate(
                      3,
                      (i) => Container(
                        width: i == step ? 24 : 8,
                        height: 8,
                        margin: const EdgeInsets.all(4),
                        decoration: BoxDecoration(
                          color: i == step ? forest : Colors.grey,
                          borderRadius: BorderRadius.circular(5),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: saving
                          ? null
                          : () => step == 2
                                ? finish()
                                : controller.nextPage(
                                    duration: const Duration(milliseconds: 250),
                                    curve: Curves.easeOut,
                                  ),
                      child: FloraText(
                        saving
                            ? 'Saving…'
                            : step == 2
                            ? 'Start exploring'
                            : 'Continue',
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class HomeScreen extends StatefulWidget {
  final AppStore store;
  const HomeScreen({super.key, required this.store});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int page = 0;
  @override
  Widget build(BuildContext context) {
    final s = widget.store;
    return Scaffold(
      appBar: AppBar(
        title: const Row(
          children: [
            Icon(Icons.spa_outlined),
            SizedBox(width: 8),
            FloraText('FloraMW', style: TextStyle(fontWeight: FontWeight.w700)),
          ],
        ),
        actions: const [
          Padding(
            padding: EdgeInsets.only(right: 16),
            child: Chip(label: FloraText('MALAWI')),
          ),
        ],
      ),
      body: SafeArea(
        child: IndexedStack(
          index: page,
          children: [
            DiscoverScreen(
              store: s,
              onIdentify: () => setState(() => page = 1),
            ),
            IdentifyScreen(store: s, service: DemoIdentificationService()),
            GardenScreen(store: s),
            SettingsScreen(
              store: s,
              replayWelcome: () => Navigator.push(
                context,
                MaterialPageRoute<void>(
                  builder: (c) => WelcomeScreen(
                    store: s,
                    onFinished: () => Navigator.pop(c),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: page,
        onDestinationSelected: (v) => setState(() => page = v),
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.explore_outlined),
            selectedIcon: const Icon(Icons.explore),
            label: s.tr('Discover', 'Onani'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.center_focus_strong),
            label: s.tr('Identify', 'Zindikirani'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.bookmark_outline),
            selectedIcon: const Icon(Icons.bookmark),
            label: s.tr('My garden', 'Munda wanga'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.settings_outlined),
            label: s.tr('Settings', 'Zokonda'),
          ),
        ],
      ),
    );
  }
}

class DiscoverScreen extends StatefulWidget {
  final AppStore store;
  final VoidCallback onIdentify;
  const DiscoverScreen({
    super.key,
    required this.store,
    required this.onIdentify,
  });
  @override
  State<DiscoverScreen> createState() => _DiscoverScreenState();
}

class _DiscoverScreenState extends State<DiscoverScreen> {
  String query = '', category = 'All plants';
  bool az = true;
  final search = TextEditingController();
  @override
  void dispose() {
    search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final results =
        plants
            .where(
              (p) =>
                  '${p.name} ${p.scientific} ${p.family}'
                      .toLowerCase()
                      .contains(query.toLowerCase()) &&
                  (category == 'All plants' || category == p.category),
            )
            .toList()
          ..sort(
            (a, b) => az ? a.name.compareTo(b.name) : b.name.compareTo(a.name),
          );
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        if (widget.store.district != null)
          FloraText(
            'Your district · ${widget.store.district}',
            style: const TextStyle(fontSize: 12),
          ),
        if (widget.store.language != 'en')
          Notice(
            '${languageNames[widget.store.language]} selected · Untranslated content appears in English. Translation review pending.',
          ),
        if (widget.store.loadWarning != null) Notice(widget.store.loadWarning!),
        const FloraText(
          'ROOTED IN MALAWI',
          style: TextStyle(
            fontSize: 11,
            letterSpacing: 2,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 14),
        FloraText(
          'A little closer\nto nature.',
          style: Theme.of(context).textTheme.displaySmall
              ?.copyWith(fontWeight: FontWeight.w600, letterSpacing: -1),
        ),
        const SizedBox(height: 14),
        const FloraText(
          'Discover flowers, explore their stories and keep a journal of what you find.',
          style: TextStyle(height: 1.6, fontSize: 16),
        ),
        const SizedBox(height: 24),
        Container(
          padding: const EdgeInsets.all(24),
          decoration: BoxDecoration(
            color: forest,
            borderRadius: BorderRadius.circular(28),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(
                Icons.filter_center_focus,
                color: Color(0xffd9e9b7),
                size: 32,
              ),
              const SizedBox(height: 20),
              const FloraText(
                'Meet your next\nbotanical discovery.',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 28,
                  height: 1.2,
                ),
              ),
              const SizedBox(height: 20),
              FilledButton.icon(
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xffd9e9b7),
                  foregroundColor: forest,
                ),
                onPressed: widget.onIdentify,
                icon: const Icon(Icons.camera_alt_outlined),
                label: FloraText(
                  widget.store.tr('Identify a flower', 'Zindikirani duwa'),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 28),
        Row(
          children: [
            Expanded(
              child: FloraText(
                'Explore the collection',
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
            IconButton(
              tooltip: az ? 'Sort Z to A' : 'Sort A to Z',
              onPressed: () => setState(() => az = !az),
              icon: const Icon(Icons.sort_by_alpha),
            ),
          ],
        ),
        const FloraText(
          'Sample catalogue · all detailed records await review',
          style: TextStyle(fontSize: 12),
        ),
        const SizedBox(height: 16),
        TextField(
          controller: search,
          onChanged: (v) => setState(() => query = v),
          decoration: InputDecoration(
            hintText: 'Search common, scientific name or family',
            prefixIcon: const Icon(Icons.search),
            suffixIcon: query.isEmpty
                ? null
                : IconButton(
                    tooltip: 'Clear search',
                    onPressed: () {
                      search.clear();
                      setState(() => query = '');
                    },
                    icon: const Icon(Icons.close),
                  ),
          ),
        ),
        const SizedBox(height: 12),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children:
                [
                      'All plants',
                      'Garden flowers',
                      'Research interest',
                      'Flowering trees',
                    ]
                    .map(
                      (c) => Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: ChoiceChip(
                          label: FloraText(c),
                          selected: category == c,
                          onSelected: (_) => setState(() => category = c),
                        ),
                      ),
                    )
                    .toList(),
          ),
        ),
        const SizedBox(height: 16),
        if (results.isEmpty)
          EmptyState(
            Icons.search_off,
            'No plants found',
            'Try another name or reset your filters.',
            action: OutlinedButton(
              onPressed: () {
                search.clear();
                setState(() {
                  query = '';
                  category = 'All plants';
                });
              },
              child: const FloraText('Reset filters'),
            ),
          ),
        ...results.map(
          (p) => PlantTile(
            p,
            onTap: () => Navigator.push(
              context,
              MaterialPageRoute<void>(
                builder: (_) => ProfileScreen(plant: p, store: widget.store),
              ),
            ),
          ),
        ),
        const SizedBox(height: 20),
        const Notice(
          'Scientific research and Malawian local beliefs are distinct types of knowledge. FloraMW labels their evidence and review status separately.',
        ),
        const SizedBox(height: 20),
      ],
    );
  }
}

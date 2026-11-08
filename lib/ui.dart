import 'localization.dart';

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import 'models.dart';

const forest = Color(0xff244c3c);
const cream = Color(0xfff6f5ee);

class PlantArt extends StatelessWidget {
  final Plant plant;
  final double height;
  const PlantArt(this.plant, {super.key, this.height = 180});
  @override
  Widget build(BuildContext context) => Semantics(
    label: 'Reference photograph of ${plant.name}; not a match for your photo',
    image: true,
    child: ClipRRect(
      borderRadius: BorderRadius.circular(24),
      child: Image.asset(
        plant.photoAsset,
        height: height,
        width: double.infinity,
        fit: BoxFit.cover,
        errorBuilder: (_, __, ___) => Container(
          height: height,
          alignment: Alignment.center,
          color: const Color(0xffe4eadb),
          child: Icon(Icons.local_florist_outlined, size: 56, color: forest),
        ),
      ),
    ),
  );
}

class PhotoView extends StatelessWidget {
  final String path;
  final double height;
  const PhotoView(this.path, {super.key, this.height = 240});
  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(24),
    child: Image.file(
      File(path),
      semanticLabel: 'Selected flower photograph',
      height: height,
      width: double.infinity,
      fit: BoxFit.cover,
      errorBuilder: (_, __, ___) => SizedBox(
        height: height,
        child: const Center(
          child: FloraText('Photo is unavailable on this device.'),
        ),
      ),
    ),
  );
}

class Notice extends StatelessWidget {
  final String text;
  final IconData icon;
  const Notice(this.text, {super.key, this.icon = Icons.info_outline});
  @override
  Widget build(BuildContext context) => Card(
    elevation: 0,
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20),
          const SizedBox(width: 12),
          Expanded(child: FloraText(text, style: const TextStyle(height: 1.5))),
        ],
      ),
    ),
  );
}

class EmptyState extends StatelessWidget {
  final IconData icon;
  final String title, body;
  final Widget? action;
  const EmptyState(this.icon, this.title, this.body, {super.key, this.action});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 36, horizontal: 16),
    child: Column(
      children: [
        Icon(icon, size: 54, color: Theme.of(context).colorScheme.primary),
        const SizedBox(height: 18),
        FloraText(
          title,
          style: Theme.of(context).textTheme.titleLarge,
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 10),
        FloraText(body, textAlign: TextAlign.center),
        if (action != null)
          Padding(padding: const EdgeInsets.only(top: 16), child: action),
      ],
    ),
  );
}

class PlantTile extends StatelessWidget {
  final Plant plant;
  final VoidCallback onTap;
  final Widget? trailing;
  const PlantTile(this.plant, {super.key, required this.onTap, this.trailing});
  @override
  Widget build(BuildContext context) => Card(
    elevation: 0,
    child: ListTile(
      contentPadding: const EdgeInsets.all(14),
      leading: SizedBox(
        width: 56,
        height: 56,
        child: PlantArt(plant, height: 56),
      ),
      title: FloraText(
        plant.name,
        style: const TextStyle(fontWeight: FontWeight.w600),
      ),
      subtitle: FloraText(
        plant.scientific,
        style: const TextStyle(fontStyle: FontStyle.italic),
      ),
      trailing: trailing ?? const Icon(Icons.arrow_outward, size: 18),
      onTap: onTap,
    ),
  );
}

Future<bool> confirm(BuildContext context, String title, String body) async =>
    await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: FloraText(title),
        content: FloraText(body),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const FloraText('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(c, true),
            child: const FloraText('Confirm'),
          ),
        ],
      ),
    ) ??
    false;
void message(BuildContext context, String text) => ScaffoldMessenger.of(
  context,
).showSnackBar(SnackBar(content: FloraText(text)));
Future<void> guarded(
  BuildContext context,
  Future<void> Function() action, {
  String? success,
}) async {
  try {
    await action();
    if (context.mounted && success != null) message(context, success);
  } catch (_) {
    if (context.mounted)
      message(
        context,
        'Could not save changes. Check available device storage and try again.',
      );
  }
}

class SourceLink extends StatelessWidget {
  final String title, url;
  const SourceLink(this.title, this.url, {super.key});
  @override
  Widget build(BuildContext context) => ListTile(
    contentPadding: EdgeInsets.zero,
    title: FloraText(title),
    subtitle: FloraText(Uri.parse(url).host),
    leading: const Icon(Icons.open_in_new),
    trailing: IconButton(
      tooltip: 'Copy source link',
      icon: const Icon(Icons.copy_outlined),
      onPressed: () async {
        await Clipboard.setData(ClipboardData(text: url));
        if (context.mounted) message(context, 'Link copied.');
      },
    ),
    onTap: () async {
      try {
        final success = await launchUrl(
          Uri.parse(url),
          mode: LaunchMode.externalApplication,
        );
        if (!success && context.mounted)
          message(context, 'Could not open browser. Use the copy link button.');
      } catch (_) {
        if (context.mounted)
          message(context, 'Could not open browser. Use the copy link button.');
      }
    },
  );
}

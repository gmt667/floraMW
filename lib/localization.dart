import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'store.dart';

class TranslationCatalog {
  static Map<String, dynamic> packs = {};
  static Future<void> load() async {
    packs = Map<String, dynamic>.from(
      jsonDecode(await rootBundle.loadString('assets/translations.json'))
          as Map,
    );
  }

  static String translate(String language, String english) {
    final pack = packs[language] as Map?;
    return (pack?['strings'] as Map?)?[english] as String? ?? english;
  }
}

class FloraScope extends InheritedNotifier<AppStore> {
  const FloraScope({super.key, required AppStore store, required super.child})
    : super(notifier: store);
  static AppStore? maybeOf(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<FloraScope>()?.notifier;
}

/// Resource-backed visible text. Unknown/unreviewed strings fall back to English.
class FloraText extends StatelessWidget {
  final String data;
  final TextStyle? style;
  final TextAlign? textAlign;
  final int? maxLines;
  final TextOverflow? overflow;
  const FloraText(
    this.data, {
    super.key,
    this.style,
    this.textAlign,
    this.maxLines,
    this.overflow,
  });
  @override
  Widget build(BuildContext context) {
    final language = FloraScope.maybeOf(context)?.language ?? 'en';
    return Text(
      TranslationCatalog.translate(language, data),
      style: style,
      textAlign: textAlign,
      maxLines: maxLines,
      overflow: overflow,
    );
  }
}

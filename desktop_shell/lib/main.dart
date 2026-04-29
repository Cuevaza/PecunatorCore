import 'dart:convert';

import 'package:flutter/material.dart';

import 'api_client.dart';

void main() {
  runApp(const PecunatorDesktopApp());
}

class PecunatorDesktopApp extends StatelessWidget {
  const PecunatorDesktopApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Pecunator Desktop',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.blueGrey),
      ),
      darkTheme: ThemeData.dark(useMaterial3: true),
      themeMode: ThemeMode.dark,
      home: const BotControlPage(),
    );
  }
}

class BotControlPage extends StatefulWidget {
  const BotControlPage({super.key});

  @override
  State<BotControlPage> createState() => _BotControlPageState();
}

class _BotControlPageState extends State<BotControlPage> {
  static const _engineBase = 'http://127.0.0.1:8765';

  final _masterCtrl = TextEditingController();
  final _tagCtrl = TextEditingController(text: 'Dorothy XRP');
  final _symbolCtrl = TextEditingController(text: 'XRPUSDT');
  final _loopCtrl = TextEditingController(text: '450');
  final _quoteCtrl = TextEditingController(text: '8');
  final _profitCtrl = TextEditingController(text: '0.05');
  final _dropCtrl = TextEditingController(text: '0.004');
  final _qtyDecCtrl = TextEditingController(text: '8');
  final _priceDecCtrl = TextEditingController(text: '4');
  final _terminalCtrl = TextEditingController(text: 'bot run_once');

  bool _simulated = true;
  bool _tradingEnabled = false;
  bool _loading = false;
  bool _terminalBusy = false;

  String _health = '-';
  String _vaultStatus = '-';
  String _botStatus = '-';
  String _gatewayStatus = '-';
  String _lastError = '-';
  String _terminalOut = '';
  String _selectedBotId = '';
  List<Map<String, dynamic>> _hubBots = <Map<String, dynamic>>[];
  String _hubLogs = '-';

  EngineApi get _api => EngineApi(_engineBase);

  @override
  void initState() {
    super.initState();
    _refreshAll();
  }

  @override
  void dispose() {
    _masterCtrl.dispose();
    _tagCtrl.dispose();
    _symbolCtrl.dispose();
    _loopCtrl.dispose();
    _quoteCtrl.dispose();
    _profitCtrl.dispose();
    _dropCtrl.dispose();
    _qtyDecCtrl.dispose();
    _priceDecCtrl.dispose();
    _terminalCtrl.dispose();
    super.dispose();
  }

  Future<void> _withBusy(Future<void> Function() fn) async {
    if (_loading) return;
    setState(() => _loading = true);
    try {
      await fn();
      _lastError = '-';
    } catch (e) {
      _lastError = e.toString();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(_lastError)),
        );
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _refreshAll() async {
    await _withBusy(() async {
      final h = await _api.health();
      final v = await _api.vaultStatus();
      final g = await _api.gatewaySnapshot();
      final hub = await _api.hubBots();
      final botsRaw = (hub['bots'] as List?) ?? const [];
      _hubBots = botsRaw.map((e) => Map<String, dynamic>.from(e as Map)).toList();
      if (_hubBots.isNotEmpty) {
        final hasSelected = _hubBots.any((b) => (b['bot_id'] ?? '').toString() == _selectedBotId);
        if (!hasSelected) {
          _selectedBotId = (_hubBots.first['bot_id'] ?? '').toString();
        }
      } else {
        _selectedBotId = '';
      }
      final selected = _hubBots.where((b) => (b['bot_id'] ?? '').toString() == _selectedBotId).toList();
      final b = selected.isNotEmpty ? selected.first : <String, dynamic>{};

      _health = jsonEncode(h);
      _vaultStatus = jsonEncode(v);
      _botStatus = jsonEncode(b);
      _gatewayStatus = jsonEncode(g);

      if (b.isNotEmpty) {
        _tagCtrl.text = (b['tag'] ?? 'Dorothy').toString();
        _symbolCtrl.text = (b['symbol'] ?? 'XRPUSDT').toString();
        _loopCtrl.text = (b['loop_interval_sec'] ?? 450).toString();
        _quoteCtrl.text = (b['quote_order_qty'] ?? '8').toString();
        _profitCtrl.text = (b['profit_factor'] ?? '0.05').toString();
        _dropCtrl.text = (b['margin_drop_factor'] ?? '0.004').toString();
        _qtyDecCtrl.text = (b['qty_decimals'] ?? 8).toString();
        _priceDecCtrl.text = (b['price_decimals'] ?? 4).toString();
        _simulated = (b['simulated'] ?? true) == true;
        _tradingEnabled = (b['trading_enabled'] ?? false) == true;
      }
      await _refreshHubLogs();
    });
  }

  Future<void> _terminalExec() async {
    final command = _terminalCtrl.text.trim();
    if (command.isEmpty || _terminalBusy) return;
    setState(() => _terminalBusy = true);
    try {
      final res = await _api.terminalExecute(
        command: command,
        masterPassword: _masterCtrl.text.trim().isEmpty ? null : _masterCtrl.text.trim(),
      );
      final output = (res['output'] ?? '').toString();
      final prev = _terminalOut.isEmpty ? '' : '$_terminalOut\n\n';
      setState(() {
        _terminalOut = '$prev> $command\n$output';
      });
    } catch (e) {
      final prev = _terminalOut.isEmpty ? '' : '$_terminalOut\n\n';
      setState(() {
        _terminalOut = '$prev> $command\nERROR: $e';
      });
    } finally {
      if (mounted) setState(() => _terminalBusy = false);
    }
  }

  Future<void> _unlockVault() async {
    await _withBusy(() async {
      await _api.unlockVault(_masterCtrl.text.trim());
      await _refreshAll();
    });
  }

  Future<void> _saveBotConfig() async {
    if (_selectedBotId.isEmpty) return;
    await _withBusy(() async {
      await _api.hubUpdateBot(_selectedBotId, {
        'tag': _tagCtrl.text.trim(),
        'symbol': _symbolCtrl.text.trim(),
        'loop_interval_sec': int.tryParse(_loopCtrl.text.trim()) ?? 450,
        'quote_order_qty': _quoteCtrl.text.trim(),
        'profit_factor': _profitCtrl.text.trim(),
        'margin_drop_factor': _dropCtrl.text.trim(),
        'qty_decimals': int.tryParse(_qtyDecCtrl.text.trim()) ?? 8,
        'price_decimals': int.tryParse(_priceDecCtrl.text.trim()) ?? 4,
        'simulated': _simulated,
        'trading_enabled': _tradingEnabled,
      });
      await _refreshAll();
    });
  }

  Future<void> _createBot() async {
    await _withBusy(() async {
      final created = await _api.hubCreateBot({
        'tag': _tagCtrl.text.trim().isEmpty ? 'Dorothy' : _tagCtrl.text.trim(),
        'symbol': _symbolCtrl.text.trim(),
        'loop_interval_sec': int.tryParse(_loopCtrl.text.trim()) ?? 450,
        'quote_order_qty': _quoteCtrl.text.trim(),
        'profit_factor': _profitCtrl.text.trim(),
        'margin_drop_factor': _dropCtrl.text.trim(),
        'qty_decimals': int.tryParse(_qtyDecCtrl.text.trim()) ?? 8,
        'price_decimals': int.tryParse(_priceDecCtrl.text.trim()) ?? 4,
        'simulated': _simulated,
        'trading_enabled': _tradingEnabled,
      });
      _selectedBotId = (created['bot_id'] ?? '').toString();
      await _refreshAll();
    });
  }

  Future<void> _startGateway() async {
    await _withBusy(() async {
      await _api.gatewayStart(
        masterPassword: _masterCtrl.text.trim().isEmpty ? null : _masterCtrl.text.trim(),
      );
      await _refreshAll();
    });
  }

  Future<void> _syncTimestamp() async {
    await _withBusy(() async {
      final res = await _api.syncTimestamp(
        masterPassword: _masterCtrl.text.trim().isEmpty ? null : _masterCtrl.text.trim(),
      );
      final out =
          'time sync: source=${res['source']} local=${res['local_time_ms']} server=${res['server_time_ms']} offset_ms=${res['offset_ms']}';
      final prev = _terminalOut.isEmpty ? '' : '$_terminalOut\n\n';
      _terminalOut = '$prev> time sync\n$out';
    });
  }

  Future<void> _stopGateway() async {
    await _withBusy(() async {
      await _api.gatewayStop();
      await _refreshAll();
    });
  }

  Future<void> _startBot() async {
    if (_selectedBotId.isEmpty) return;
    await _withBusy(() async {
      await _api.hubStartBot(
        _selectedBotId,
        masterPassword: _masterCtrl.text.trim().isEmpty ? null : _masterCtrl.text.trim(),
      );
      await _refreshAll();
    });
  }

  Future<void> _stopBot() async {
    if (_selectedBotId.isEmpty) return;
    await _withBusy(() async {
      await _api.hubStopBot(_selectedBotId);
      await _refreshAll();
    });
  }

  Future<void> _runOnce() async {
    if (_selectedBotId.isEmpty) return;
    await _withBusy(() async {
      await _api.hubRunOnce(
        _selectedBotId,
        masterPassword: _masterCtrl.text.trim().isEmpty ? null : _masterCtrl.text.trim(),
      );
      await _refreshAll();
    });
  }

  Future<void> _deleteBot() async {
    if (_selectedBotId.isEmpty) return;
    await _withBusy(() async {
      await _api.hubDeleteBot(_selectedBotId);
      await _refreshAll();
    });
  }

  Future<void> _refreshHubLogs() async {
    if (_selectedBotId.isEmpty) {
      _hubLogs = '-';
      return;
    }
    final logs = await _api.hubLogs(_selectedBotId, limit: 120);
    _hubLogs = jsonEncode(logs);
  }

  Widget _kv(String title, String body) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            SelectableText(
              body,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('PecunatorCore · Dorothy Hub'),
        actions: [
          IconButton(
            onPressed: _loading ? null : _refreshAll,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Engine connection is local/internal and fixed. No browser dashboard, no URL input in UI.',
              style: TextStyle(fontSize: 12, color: Colors.grey),
            ),
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Dorothy Hub', style: TextStyle(fontWeight: FontWeight.bold)),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Expanded(
                          child: InputDecorator(
                            decoration: const InputDecoration(
                              labelText: 'Instancia activa',
                              border: OutlineInputBorder(),
                              contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                            ),
                            child: DropdownButtonHideUnderline(
                              child: DropdownButton<String>(
                                isExpanded: true,
                                value: _selectedBotId.isEmpty ? null : _selectedBotId,
                                items: _hubBots
                                    .map(
                                      (b) => DropdownMenuItem<String>(
                                        value: (b['bot_id'] ?? '').toString(),
                                        child: Text(
                                          '${(b['tag'] ?? '-')} · ${(b['symbol'] ?? '-')} · ${(b['running'] == true ? 'RUNNING' : 'STOPPED')}',
                                        ),
                                      ),
                                    )
                                    .toList(),
                                onChanged: _loading
                                    ? null
                                    : (v) async {
                                        setState(() => _selectedBotId = v ?? '');
                                        await _refreshAll();
                                      },
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        SizedBox(
                          width: 260,
                          child: TextField(
                            controller: _tagCtrl,
                            decoration: const InputDecoration(
                              labelText: 'Tag descriptivo',
                              border: OutlineInputBorder(),
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        ElevatedButton(
                          onPressed: _loading ? null : _createBot,
                          child: const Text('Crear Dorothy'),
                        ),
                        const SizedBox(width: 8),
                        OutlinedButton(
                          onPressed: _loading || _selectedBotId.isEmpty ? null : _deleteBot,
                          child: const Text('Eliminar'),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Container(
                      width: double.infinity,
                      constraints: const BoxConstraints(minHeight: 90, maxHeight: 180),
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        border: Border.all(color: Colors.white24),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: SingleChildScrollView(
                        child: SelectableText(
                          _hubLogs,
                          style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _masterCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Master password (vault)',
                      border: OutlineInputBorder(),
                    ),
                    obscureText: true,
                  ),
                ),
                const SizedBox(width: 8),
                ElevatedButton(
                  onPressed: _loading ? null : _unlockVault,
                  child: const Text('Unlock vault'),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                SizedBox(
                  width: 250,
                  child: TextField(
                    controller: _symbolCtrl,
                    decoration: const InputDecoration(labelText: 'Symbol', border: OutlineInputBorder()),
                  ),
                ),
                SizedBox(
                  width: 200,
                  child: TextField(
                    controller: _loopCtrl,
                    decoration: const InputDecoration(labelText: 'Loop sec', border: OutlineInputBorder()),
                  ),
                ),
                SizedBox(
                  width: 200,
                  child: TextField(
                    controller: _quoteCtrl,
                    decoration: const InputDecoration(labelText: 'Quote order qty', border: OutlineInputBorder()),
                  ),
                ),
                SizedBox(
                  width: 200,
                  child: TextField(
                    controller: _profitCtrl,
                    decoration: const InputDecoration(labelText: 'Profit factor', border: OutlineInputBorder()),
                  ),
                ),
                SizedBox(
                  width: 220,
                  child: TextField(
                    controller: _dropCtrl,
                    decoration: const InputDecoration(labelText: 'Margin drop factor', border: OutlineInputBorder()),
                  ),
                ),
                SizedBox(
                  width: 180,
                  child: TextField(
                    controller: _qtyDecCtrl,
                    decoration: const InputDecoration(labelText: 'Qty decimals', border: OutlineInputBorder()),
                  ),
                ),
                SizedBox(
                  width: 180,
                  child: TextField(
                    controller: _priceDecCtrl,
                    decoration: const InputDecoration(labelText: 'Price decimals', border: OutlineInputBorder()),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 24,
              children: [
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text('Simulated mode'),
                    Switch(
                      value: _simulated,
                      onChanged: _loading ? null : (v) => setState(() => _simulated = v),
                    ),
                  ],
                ),
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text('Trading enabled (LIVE guard)'),
                    Switch(
                      value: _tradingEnabled,
                      onChanged: _loading ? null : (v) => setState(() => _tradingEnabled = v),
                    ),
                  ],
                ),
                if (!_simulated && !_tradingEnabled)
                  const Text(
                    'LIVE guard active: set trading_enabled=true to allow real orders.',
                    style: TextStyle(color: Colors.deepOrange),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                ElevatedButton(
                  onPressed: _loading ? null : _saveBotConfig,
                  child: const Text('Save bot config'),
                ),
                ElevatedButton(
                  onPressed: _loading ? null : _startGateway,
                  child: const Text('Start gateway'),
                ),
                OutlinedButton(
                  onPressed: _loading ? null : _stopGateway,
                  child: const Text('Stop gateway'),
                ),
                ElevatedButton(
                  onPressed: _loading ? null : _startBot,
                  child: const Text('Start bot loop'),
                ),
                OutlinedButton(
                  onPressed: _loading ? null : _stopBot,
                  child: const Text('Stop bot loop'),
                ),
                OutlinedButton(
                  onPressed: _loading ? null : _runOnce,
                  child: const Text('Run once'),
                ),
                ElevatedButton(
                  onPressed: _loading ? null : _syncTimestamp,
                  child: const Text('Sync timestamp'),
                ),
              ],
            ),
            const SizedBox(height: 12),
            if (_loading) const LinearProgressIndicator(),
            _kv('Health', _health),
            _kv('Vault status', _vaultStatus),
            _kv('Gateway snapshot', _gatewayStatus),
            _kv('Bot status', _botStatus),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Terminal (API in situ)',
                      style: TextStyle(fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Expanded(
                          child: TextField(
                            controller: _terminalCtrl,
                            decoration: const InputDecoration(
                              labelText: 'Command',
                              hintText: 'bot run_once | bot start | gateway start | account | price BTCUSDT',
                              border: OutlineInputBorder(),
                            ),
                            onSubmitted: (_) => _terminalExec(),
                          ),
                        ),
                        const SizedBox(width: 8),
                        ElevatedButton(
                          onPressed: _terminalBusy ? null : _terminalExec,
                          child: const Text('Execute'),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Container(
                      width: double.infinity,
                      constraints: const BoxConstraints(minHeight: 120, maxHeight: 260),
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        border: Border.all(color: Colors.white24),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: SingleChildScrollView(
                        child: SelectableText(
                          _terminalOut.isEmpty ? '(no output yet)' : _terminalOut,
                          style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            _kv('Last error', _lastError),
          ],
        ),
      ),
    );
  }
}

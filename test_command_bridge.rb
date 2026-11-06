# frozen_string_literal: true

require 'minitest/autorun'
require 'tmpdir'
require 'json'
require 'socket'
require 'timeout'

# Read native implementations, never require Lich's startup or touch a session.
# A checkout can be supplied explicitly; CI may skip only the native integration
# cases when that external source is absent. Bridge/security tests always run.
LICH_LIB = ENV.fetch('GEMPY_TEST_LICH_LIB', '/home/nick/gs4/Lich5/lib')
NATIVE_SOURCE = File.file?(File.join(LICH_LIB, 'global_defs.rb'))
if NATIVE_SOURCE
  require File.join(LICH_LIB, 'common/client_input_dispatcher')
  require File.join(LICH_LIB, 'main/user_exit_dispatch')
  require File.join(LICH_LIB, 'common/shutdown_script_drain')
  LIB_DIR = LICH_LIB
  require File.join(LICH_LIB, 'common/client_commands/builtins')
  source = File.read(File.join(LICH_LIB, 'global_defs.rb'))
  start = source.index("def dispatch_client_input(client_string)\n")
  finish = source.index("\ndef report_errors", start)
  Object.class_eval(source[start...finish], File.join(LICH_LIB, 'global_defs.rb'), source[0...start].count("\n") + 1)
else
  # Core security/transport cases still run without a Lich checkout. These
  # stand-ins are used only there; native routing cases explicitly skip.
  module Lich
    module Common
      module ClientInputDispatcher
        @mutex = Mutex.new
        def self.dispatch(line) = @mutex.synchronize { yield line }
      end
      module ShutdownCoordinator
        def self.requested? = false
      end
    end
    module Main
      module UserExitDispatch
        def self.dispatch_detachable_client(*) = false
      end
    end
  end
  def dispatch_client_input(line)
    Lich::Common::ClientInputDispatcher.dispatch(line) { |input| do_client(input) }
  end
  def do_client(line)
    line = UpstreamHook.run(line)
    Game._puts(line) if line
  end
end

load File.join(__dir__, 'scripts/gempy_control.lic') if File.file?(File.join(__dir__, 'scripts/gempy_control.lic'))

# Fakes stop at external effects. Native serialization, upstream processing,
# built-in routing, and exit detection execute the read-only checkout's source.
module BridgeNativeFixtures
  class SocketState
    attr_accessor :closed
    def closed? = !!@closed
  end
  class Game
    class << self
      attr_accessor :socket, :writes, :eof
      def open(*)
        @socket = SocketState.new
        @eof = false
      end
      def close = @socket.closed = true
      def closed? = !@socket || @socket.closed?
      def remote_eof? = !!@eof
      def thread = Thread.main
      def reader_thread = Thread.main
      def autostarted? = true
      def _puts(line) = @writes << line.dup
    end
  end
  module XMLData
    def self.name = 'Fixture'
    def self.game = 'GSIV'
  end
  module Char
    def self.name = 'Fixture'
  end
  module UpstreamHook
    class << self
      attr_accessor :hook, :lines
      def run(line)
        @lines << line.dup
        @hook ? @hook.call(line) : line
      end
    end
  end
  module Frontend
    def self.supports_gsl? = true
  end
  module Script
    class << self
      attr_accessor :starts, :upstream, :scripts
      def start(*args) = @starts << args
      def new_upstream(line) = @upstream << line.dup
      def running = @scripts
      def current = nil
    end
  end
end
Game = BridgeNativeFixtures::Game
XMLData = BridgeNativeFixtures::XMLData
Char = BridgeNativeFixtures::Char
UpstreamHook = BridgeNativeFixtures::UpstreamHook
Frontend = BridgeNativeFixtures::Frontend
Script = BridgeNativeFixtures::Script

class CommandBridgeTest < Minitest::Test
  def setup
    assert defined?(GempyControl), 'command bridge implementation is missing'
    skip 'read-only Lich source unavailable; set GEMPY_TEST_LICH_LIB' if name.start_with?('test_native_') && !NATIVE_SOURCE
    Game.open
    Game.writes = []
    UpstreamHook.lines = []
    UpstreamHook.hook = nil
    Script.starts = []
    Script.upstream = []
    Script.scripts = []
    $_CLIENTBUFFER_ = []
    $cmd_prefix = ''
    $lich_char_regex = ';'
    $offline_mode = false
    @now = Time.now.to_f
    @runtime = GempyControl::Runtime.new
    @bridge = GempyControl::Bridge.new(runtime: @runtime, clock: -> { @now }, capacity: 2)
  end

  def identity = @bridge.record
  def request(action = 'dispatch', **attrs)
    identity.merge('action' => action, 'request_id' => 'request-1', 'command' => 'look', 'deadline' => @now + 5).merge(attrs.transform_keys(&:to_s))
  end
  def send_request(req) = @bridge.handle(req, peer_uid: Process.uid)
  def test_native_literal_game_input_is_not_split_or_expanded
    assert_equal 'sent', send_request(request(command: 'say  a;$(ignored)'))['state']
    assert_equal ['say  a;$(ignored)'], Game.writes
    assert_equal ['say  a;$(ignored)'], UpstreamHook.lines
  end

  def test_native_script_routing_and_prefix
    $cmd_prefix = '<c>'
    assert_equal 'sent', send_request(request(command: ';fixture_script Arg  two'))['state']
    assert_equal [['fixture_script', 'Arg  two']], Script.starts
    assert_empty Game.writes
    assert_equal ['<c>;fixture_script Arg  two'], UpstreamHook.lines
  end

  def test_native_builtin_and_hook_consumption
    script = Struct.new(:no_pause_all, :paused) do
      def paused? = !!paused
      def pause = self.paused = true
    end.new(false, false)
    Script.scripts = [script]
    assert_equal 'sent', send_request(request(command: ';pause all'))['state']
    assert script.paused?
    UpstreamHook.hook = ->(_) { nil }
    assert_equal 'sent', send_request(request(request_id: 'request-2'))['state']
    assert_empty Game.writes
  end

  def test_native_exit_routing_arms_watchdog_before_orderly_exit
    events = []
    shutdown = Lich::Common::OrderlyShutdown
    watchdog = Lich::Common::ShutdownWatchdog
    shutdown_original = shutdown.method(:request_user_exit)
    watchdog_original = watchdog.method(:arm)
    shutdown.define_singleton_method(:request_user_exit) { |**options| events << [:exit, options] }
    watchdog.define_singleton_method(:arm) { events << [:watchdog] }
    $cmd_prefix = '<c>'
    assert_equal 'sent', send_request(request(command: 'quit'))['state']
    assert_equal :watchdog, events[0][0]
    assert_equal '<c>quit', events[1][1][:server_exit_command]
    assert_empty UpstreamHook.lines
    assert_empty Game.writes
  ensure
    shutdown&.define_singleton_method(:request_user_exit, shutdown_original) if shutdown_original
    watchdog&.define_singleton_method(:arm, watchdog_original) if watchdog_original
  end

  def test_native_orderly_exit_runs_real_shutdown_sequence_against_isolated_effects
    events = []
    shutdown = Lich::Common::OrderlyShutdown
    watchdog = Lich::Common::ShutdownWatchdog
    coordinator = Lich::Common::ShutdownCoordinator
    shutdown_original = shutdown.method(:request_user_exit)
    watchdog_original = watchdog.method(:arm)
    vars = Object.new
    vars.define_singleton_method(:save) { events << :save_vars }
    reader = Object.new
    reader.define_singleton_method(:join) { |_| events << :wait_eof; true }
    game = Object.new
    game.define_singleton_method(:_puts) { |line| events << [:wire_exit, line]; true }
    game.define_singleton_method(:reader_thread) { reader }
    game.define_singleton_method(:remote_eof?) { true }
    game.define_singleton_method(:close) { events << :close_game }
    shutdown.define_singleton_method(:request_user_exit) do |**options|
      shutdown_original.call(**options, vars: vars, game: game, scripts_provider: -> { [] })
    end
    watchdog.define_singleton_method(:arm) { events << :watchdog }
    $cmd_prefix = '<c>'
    assert_equal 'sent', send_request(request(command: 'exit'))['state']
    assert_equal [:watchdog, :save_vars, [:wire_exit, '<c>exit'], :wait_eof, :close_game], events
    assert coordinator.orderly_shutdown_completed?
    assert_empty UpstreamHook.lines
  ensure
    shutdown&.define_singleton_method(:request_user_exit, shutdown_original) if shutdown_original
    watchdog&.define_singleton_method(:arm, watchdog_original) if watchdog_original
    coordinator&.instance_variable_set(:@request, nil)
    coordinator&.instance_variable_set(:@orderly_shutdown_result, nil)
    Lich::Common::ShutdownLog.flush_user_exit_summary! if defined?(Lich::Common::ShutdownLog)
  end

  def test_full_identity_and_same_user_are_mandatory
    %w[protocol pid process_start session_id bridge_generation character realm].each do |key|
      bad = request.merge(key => 'wrong')
      assert_equal 'not_sent', send_request(bad)['state'], key
    end
    assert_equal 'not_sent', @bridge.handle(request, peer_uid: Process.uid + 1)['state']
    assert_empty Game.writes
  end

  def test_binary_source_compiles_like_lich_script_loader
    source = File.binread(File.join(__dir__, 'scripts/gempy_control.lic'))
    assert RubyVM::InstructionSequence.compile(source), 'binary-evaluated Lich script must compile'
  end

  def test_invalid_commands_never_enter_native_hooks
    ['', '   ', "a\nb", "a\rb", "a\0b", "a\tb", "a\u007fb", "a\u0085b", 'é' * 513, nil].each do |command|
      assert_equal 'not_sent', send_request(request(command: command))['state']
    end
    assert_empty UpstreamHook.lines
  end

  def test_deadline_rejected_and_remembered_without_replay
    req = request(deadline: @now - 1)
    assert_equal 'not_sent', send_request(req)['state']
    @now -= 2
    assert_equal 'not_sent', send_request(req)['state']
    assert_empty Game.writes
  end

  def test_duplicate_changed_payload_and_full_cache
    req = request
    assert_equal 'sent', send_request(req)['state']
    assert_equal 'sent', send_request(req)['state']
    assert_equal 'request_conflict', send_request(req.merge('command' => 'south'))['reason']
    assert_equal 'request_conflict', send_request(req.merge('deadline' => @now + 10))['reason']
    assert_equal 'sent', send_request(request(request_id: 'request-2'))['state']
    assert_equal 'cache_full', send_request(request(request_id: 'request-3'))['reason']
    assert_equal ['look', 'look'], Game.writes
    assert_equal 'sent', send_request(req)['state']
  end

  def test_expiration_after_waiting_for_native_mutex
    entered, release = Queue.new, Queue.new
    holder = Thread.new { Lich::Common::ClientInputDispatcher.dispatch('frontend') { entered << true; release.pop } }
    entered.pop
    req = request
    worker = Thread.new { send_request(req) }
    Timeout.timeout(2) { sleep 0.001 until send_request(request('receipt'))['state'] == 'sending' }
    @now += 6
    assert_equal 'not_sent', send_request(request('receipt'))['state']
    release << true
    assert_equal 'not_sent', worker.value['state']
    assert_empty UpstreamHook.lines
    assert_equal 'not_sent', send_request(req)['state']
  ensure
    release << true if release
    holder&.join(1)
    worker&.kill
  end

  def test_socket_dispatch_uses_frontend_thread_group_instead_of_bridge_script_group
    Dir.mktmpdir do |dir|
      created = Queue.new
      owner = Thread.new do
        script_group = ThreadGroup.new
        script_group.add(Thread.current)
        server = GempyControl::Server.new(directory: dir, bridge: @bridge)
        server.start
        created << server
      end
      server = created.pop
      owner.join
      native_group = Queue.new
      UpstreamHook.hook = ->(line) { native_group << Thread.current.group; line }
      record = JSON.parse(File.read(File.join(dir, "#{Process.pid}.json")))
      UNIXSocket.open(File.join(dir, record.fetch('socket'))) do |socket|
        socket.puts(JSON.generate(request))
        assert_equal 'sent', JSON.parse(Timeout.timeout(2) { socket.gets })['state']
      end
      assert_same ThreadGroup::Default, native_group.pop
    ensure
      server&.stop
    end
  end

  def test_blocked_native_hook_keeps_receipts_responsive_and_no_duplicate
    entered, release = Queue.new, Queue.new
    UpstreamHook.hook = ->(line) { entered << true; release.pop; line }
    req = request
    worker = Thread.new { send_request(req) }
    entered.pop
    @now += 10
    assert_equal 'sending', Timeout.timeout(1) { send_request(request('receipt')) }['state']
    assert_equal 'sending', Timeout.timeout(1) { send_request(req) }['state']
    release << true
    assert_equal 'sent', worker.value['state']
    assert_equal ['look'], Game.writes
    assert_equal 'sent', send_request(request('receipt'))['state']
  ensure
    worker&.kill
  end

  def test_reconnect_during_native_lock_wait_rejects_original_identity
    entered, release = Queue.new, Queue.new
    holder = Thread.new { Lich::Common::ClientInputDispatcher.dispatch('frontend') { entered << true; release.pop } }
    entered.pop
    worker = Thread.new { send_request(request) }
    Timeout.timeout(2) { sleep 0.001 until send_request(request('receipt'))['state'] == 'sending' }
    Game.close
    Game.open
    release << true
    assert_equal 'not_sent', worker.value['state']
    assert_empty UpstreamHook.lines
  ensure
    release << true if release
    holder&.join(1)
    worker&.kill
  end

  def test_stop_during_native_lock_wait_never_admits_pending_input
    entered, release = Queue.new, Queue.new
    holder = Thread.new { Lich::Common::ClientInputDispatcher.dispatch('frontend') { entered << true; release.pop } }
    entered.pop
    worker = Thread.new { send_request(request) }
    Timeout.timeout(2) { sleep 0.001 until send_request(request('receipt'))['state'] == 'sending' }
    @bridge.stop
    release << true
    assert_equal 'not_sent', worker.value['state']
    assert_empty UpstreamHook.lines
  ensure
    release << true if release
    holder&.join(1)
    worker&.kill
  end

  def test_pending_shutdown_is_not_command_ready
    coordinator = Lich::Common::ShutdownCoordinator
    original = coordinator.method(:requested?)
    coordinator.define_singleton_method(:requested?) { true }
    refute send_request(request('ping'))['ready']
    assert_equal 'not_sent', send_request(request)['state']
    assert_empty UpstreamHook.lines
  ensure
    coordinator&.define_singleton_method(:requested?, original) if original
  end

  def test_exception_after_admission_is_unconfirmed_and_never_replayed
    UpstreamHook.hook = ->(_) { raise 'hook failed after effects' }
    req = request
    assert_equal 'unconfirmed', send_request(req)['state']
    assert_equal 'unconfirmed', send_request(req)['state']
    assert_equal ['look'], UpstreamHook.lines
  end

  def test_reconnect_without_intermediate_poll_rotates_generation
    old = request
    generation = identity['bridge_generation']
    Game.close
    Game.open
    refute_equal generation, identity['bridge_generation']
    assert_equal 'not_sent', send_request(old)['state']
    assert_empty Game.writes
  end

  def test_runtime_readiness_refuses_offline_eof_shutdown_or_missing_capability
    assert send_request(request('ping'))['ready']
    Game.eof = true
    refute send_request(request('ping'))['ready']
    assert_equal 'not_sent', send_request(request)['state']
    Game.eof = false
    $offline_mode = true
    refute send_request(request('ping'))['ready']
    $offline_mode = false
    original = Game.method(:remote_eof?)
    Game.singleton_class.send(:undef_method, :remote_eof?)
    refute send_request(request('ping'))['ready']
    assert_empty UpstreamHook.lines
  ensure
    Game.define_singleton_method(:remote_eof?, original) if original
  end

  def test_unknown_receipt_never_dispatches
    reply = send_request(request('receipt'))
    assert_equal 'unknown_request', reply['reason']
    assert_empty Game.writes
  end

  def test_private_socket_record_protocol_and_responsive_receipt
    Dir.mktmpdir do |dir|
      server = GempyControl::Server.new(directory: dir, bridge: @bridge)
      server.start
      record = JSON.parse(File.read(File.join(dir, "#{Process.pid}.json")))
      assert_equal 0o700, File.stat(dir).mode & 0o777
      assert_equal 0o600, File.stat(File.join(dir, record.fetch('socket'))).mode & 0o777
      assert_equal 0o600, File.stat(File.join(dir, "#{Process.pid}.json")).mode & 0o777
      exchange = lambda do |req|
        UNIXSocket.open(File.join(dir, record['socket'])) do |socket|
          socket.puts(JSON.generate(req))
          Timeout.timeout(2) { JSON.parse(socket.gets) }
        end
      end
      assert exchange.call(request('ping'))['ready']
      entered, release = Queue.new, Queue.new
      UpstreamHook.hook = ->(line) { entered << true; release.pop; line }
      worker = Thread.new { exchange.call(request) }
      entered.pop
      assert_equal 'sending', exchange.call(request('receipt'))['state']
      release << true
      assert_equal 'sent', worker.value['state']
      Game.close
      Game.open
      server.refresh
      changed = JSON.parse(File.read(File.join(dir, "#{Process.pid}.json")))
      refute_equal record['socket'], changed['socket']
      refute File.exist?(File.join(dir, record['socket']))
    ensure
      worker&.kill
      server&.stop
    end
  end

  def test_unsafe_directory_or_existing_record_is_never_replaced
    Dir.mktmpdir do |dir|
      File.chmod(0o755, dir)
      assert_raises(SecurityError) { GempyControl::Server.new(directory: dir, bridge: @bridge).start }
      File.chmod(0o700, dir)
      path = File.join(dir, "#{Process.pid}.json")
      File.write(path, 'existing bridge')
      assert_raises(SecurityError) { GempyControl::Server.new(directory: dir, bridge: @bridge).start }
      assert_equal 'existing bridge', File.read(path)
    end
  end

  def test_runtime_that_cannot_create_frontend_threads_never_publishes_readiness
    Dir.mktmpdir do |dir|
      result = Queue.new
      owner = Thread.new do
        group = ThreadGroup.new
        group.add(Thread.current)
        group.enclose
        begin
          server = GempyControl::Server.new(directory: dir, bridge: @bridge)
          server.start
          result << :incorrectly_started
        rescue ThreadError
          result << :refused
        ensure
          server&.stop
        end
      end
      actual = Timeout.timeout(2) { result.pop }
      owner.join
      assert_equal :refused, actual
      assert_empty Dir.children(dir)
    end
  end

  def test_concurrent_socket_workers_keep_their_own_client
    Dir.mktmpdir do |dir|
      accepted, release = Queue.new, Queue.new
      server_class = Class.new(GempyControl::Server) do
        define_method(:frontend_thread) do |*args, &block|
          @thread_count = @thread_count.to_i + 1
          if @thread_count == 1
            super(*args, &block)
          else
            super(*args) { |*values| accepted << true; release.pop; block.call(*values) }
          end
        end
      end
      server = server_class.new(directory: dir, bridge: @bridge).start
      record = JSON.parse(File.read(File.join(dir, "#{Process.pid}.json")))
      first = UNIXSocket.new(File.join(dir, record['socket']))
      second = UNIXSocket.new(File.join(dir, record['socket']))
      first.puts(JSON.generate(request(command: 'first')))
      second.puts(JSON.generate(request(request_id: 'request-2', command: 'second')))
      2.times { Timeout.timeout(2) { accepted.pop } }
      2.times { release << true }
      replies = Timeout.timeout(2) { [JSON.parse(first.gets), JSON.parse(second.gets)] }
      replies.each { |reply| assert_includes %w[sent not_sent], reply['state'] }
      expected_writes = ['first', 'second'].zip(replies).filter_map { |line, reply| line if reply['state'] == 'sent' }
      assert_equal expected_writes.sort, Game.writes.sort
      refute_empty Game.writes
    ensure
      2.times { release << true } if release
      first&.close
      second&.close
      server&.stop
    end
  end

  def test_overlapping_script_cleanup_and_ensure_stop_are_idempotent
    Dir.mktmpdir do |dir|
      server = GempyControl::Server.new(directory: dir, bridge: @bridge).start
      original = File.method(:unlink)
      record_path = File.join(dir, "#{Process.pid}.json")
      reached, release = Queue.new, Queue.new
      File.define_singleton_method(:unlink) do |path|
        if path == record_path
          reached << true
          release.pop
        end
        original.call(path)
      end
      workers = 2.times.map do
        Thread.new do
          begin
            server.stop
            nil
          rescue StandardError => error
            error
          end
        end
      end
      Timeout.timeout(2) { reached.pop }
      sleep 0.01
      2.times { release << true }
      assert_equal [nil, nil], workers.map(&:value)
      assert_empty Dir.children(dir)
    ensure
      2.times { release << true } if release
      File.define_singleton_method(:unlink, original) if original
      server&.stop
    end
  end

  def test_blocked_dispatch_saturation_does_not_consume_receipt_or_ping_handlers
    attempted = Queue.new
    native = @runtime
    runtime = Object.new
    runtime.define_singleton_method(:snapshot) { native.snapshot }
    runtime.define_singleton_method(:dispatch) do |command, &guard|
      attempted << true
      native.dispatch(command, &guard)
    end
    @bridge = GempyControl::Bridge.new(runtime: runtime, clock: -> { @now }, capacity: 64)
    entered, release = Queue.new, Queue.new
    UpstreamHook.hook = ->(line) { entered << true; release.pop; line }
    Dir.mktmpdir do |dir|
      server = GempyControl::Server.new(directory: dir, bridge: @bridge).start
      record = JSON.parse(File.read(File.join(dir, "#{Process.pid}.json")))
      path = File.join(dir, record.fetch('socket'))
      clients = []
      first = UNIXSocket.new(path)
      first.puts(JSON.generate(request(request_id: 'saturation-0')))
      clients << first
      Timeout.timeout(2) { entered.pop }
      31.times do |index|
        socket = UNIXSocket.new(path)
        socket.puts(JSON.generate(request(request_id: "saturation-#{index + 1}")))
        clients << socket
      end
      # Before the fix every dispatch waits forever in native serialization.
      # After the fix only the reserved handler enters; others finish busy.
      begin
        Timeout.timeout(0.1) { sleep 0.001 until attempted.size == 32 }
      rescue Timeout::Error
        nil
      end
      reply = begin
        UNIXSocket.open(path) do |socket|
          socket.puts(JSON.generate(request('receipt', request_id: 'saturation-0')))
          Timeout.timeout(0.5) { JSON.parse(socket.gets) }
        end
      rescue StandardError => error
        { 'state' => error.class.name }
      end
      assert_equal 'sending', reply['state']
      UNIXSocket.open(path) do |socket|
        socket.puts(JSON.generate(request('ping')))
        assert Timeout.timeout(0.5) { JSON.parse(socket.gets) }['ready']
      end
      assert_equal 1, attempted.size
    ensure
      clients&.each { |socket| socket.close rescue nil }
      server&.stop
      32.times { release << true } if release
      server&.instance_variable_get(:@clients)&.each { |thread, _| thread.join(1) }
    end
  end

  def test_busy_rejection_is_cached_and_never_runs_when_reservation_clears
    @bridge = GempyControl::Bridge.new(runtime: @runtime, clock: -> { @now }, capacity: 3)
    entered, release = Queue.new, Queue.new
    UpstreamHook.hook = ->(line) { entered << true; release.pop; line }
    worker = Thread.new { send_request(request) }
    Timeout.timeout(2) { entered.pop }
    busy = request(request_id: 'request-2', command: 'must never run')
    reply = Timeout.timeout(0.5) { send_request(busy) }
    assert_equal 'not_sent', reply['state']
    assert_equal 'busy', reply['reason']
    release << true
    assert_equal 'sent', worker.value['state']
    UpstreamHook.hook = nil
    assert_equal 'busy', send_request(busy)['reason']
    assert_equal 'sent', send_request(request(request_id: 'request-3', command: 'new command'))['state']
    assert_equal ['look', 'new command'], Game.writes
  ensure
    release << true if release
    worker&.join(1)
    worker&.kill
  end
end

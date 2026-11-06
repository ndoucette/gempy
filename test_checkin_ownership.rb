require 'minitest/autorun'
require_relative 'scripts/gempy_checkin_ownership'

class CheckinOwnershipTest < Minitest::Test
  def setup
    @attached = []
    @exits = 0
    @guard = GempyCheckinOwnership::Arbiter.new(capture_id: 'a' * 48,
      attached: -> { @attached.dup }, ready: -> { true }, logout: -> { @exits += 1 })
  end

  def test_logout_requires_matching_attempt_and_ready_runtime
    assert_equal 'denied', @guard.command('logout', 'b' * 48)['state']
    assert_equal 0, @exits
    assert_equal 'logging_out', @guard.command('logout', 'a' * 48)['state']
    assert_equal 1, @exits
    @guard.command('logout', 'a' * 48)
    assert_equal 1, @exits
  end

  def test_logout_acknowledged_before_game_shutdown
    events = []
    guard = GempyCheckinOwnership::Arbiter.new(capture_id: 'a'*48,
      attached: -> { [] }, ready: -> { true }, logout: -> { events << :exit })
    guard.command('logout', 'a'*48) { |reply| events << :ack if reply['state'] == 'logging_out' }
    assert_equal [:ack, :exit], events
  end

  def test_external_attachment_permanently_disarms_exit_even_after_detach
    @guard.register { @attached << :client }
    @attached.clear
    assert_equal 'user_owned', @guard.command('logout', 'a' * 48)['state']
    assert_equal 0, @exits
  end

  def test_takeover_ack_and_late_attachment
    assert_equal 'user_owned', @guard.command('takeover', 'a' * 48)['state']
    @guard.command('logout', 'a' * 48)
    assert_equal 0, @exits
  end

  def test_logout_wins_race_and_never_registers_late_client
    entered = Queue.new
    release = Queue.new
    @guard = GempyCheckinOwnership::Arbiter.new(capture_id: 'a' * 48,
      attached: -> { [] }, ready: -> { true }, logout: -> { entered << true; release.pop })
    closer = Thread.new { @guard.command('logout', 'a' * 48) }
    entered.pop
    registered = false
    assert_equal false, @guard.register { registered = true }
    assert_equal false, registered
    assert_equal 'logging_out', @guard.command('takeover', 'a' * 48)['state']
    release << true
    closer.join
  end

  def test_attachment_wins_race
    entered = Queue.new
    release = Queue.new
    client = Thread.new { @guard.register { entered << true; release.pop } }
    entered.pop
    closer = Thread.new { @guard.command('logout', 'a' * 48) }
    release << true
    client.join
    assert_equal 'user_owned', closer.value['state']
    assert_equal 0, @exits
  end

  def test_missing_detection_or_runtime_fails_closed
    [-> { nil }, -> { raise 'unavailable' }].each do |snapshot|
      guard = GempyCheckinOwnership::Arbiter.new(capture_id: 'a' * 48,
        attached: snapshot, ready: -> { true }, logout: -> { @exits += 1 })
      assert_equal 'uncertain', guard.command('logout', 'a' * 48)['state']
    end
    guard = GempyCheckinOwnership::Arbiter.new(capture_id: 'a' * 48,
      attached: -> { [] }, ready: -> { false }, logout: -> { @exits += 1 })
    assert_equal 'unavailable', guard.command('logout', 'a' * 48)['state']
    assert_equal 0, @exits
  end
end

class StartupBarrierTest < Minitest::Test
  ScriptResult = Struct.new(:name, :running, :success, :error) do
    def running?; running; end
    def completed_successfully?; success && !error; end
  end
  def test_completed_scripts_and_background_are_distinguished
    barrier = GempyCheckinOwnership::StartupBarrier.new(required: %w[autostart finite reporter], background: %w[reporter])
    parent = ScriptResult.new('autostart', false, true)
    finite = ScriptResult.new('finite', true, false)
    reporter = ScriptResult.new('reporter', true, false)
    [parent, finite, reporter].each { |s| barrier.record(s) }
    refute barrier.snapshot['ready']
    finite.running = false
    refute barrier.snapshot['ready'], 'disappearance alone must never certify startup'
    finite.success = true
    assert barrier.snapshot['ready']
    child = ScriptResult.new('delayed_child', true, false)
    barrier.record(child)
    refute barrier.snapshot['ready'], 'observed child work is part of the barrier'
  end
  def test_command_bridge_can_keep_running_after_login_scripts_finish
    barrier = GempyCheckinOwnership::StartupBarrier.new(
      required: %w[autostart lumnismon gempy_reporter], background: %w[gempy_reporter])
    autostart = ScriptResult.new('autostart', false, true)
    lumnismon = ScriptResult.new('lumnismon', true, false)
    reporter = ScriptResult.new('gempy_reporter', true, false)
    bridge = ScriptResult.new('gempy_control', true, false)
    [autostart, lumnismon, reporter, bridge].each { |script| barrier.record(script) }
    refute barrier.snapshot['ready'], 'finite login work must still finish'
    lumnismon.running = false
    lumnismon.success = true
    assert barrier.snapshot['ready'], 'the persistent command bridge must not block capture'
    assert_equal 'background', barrier.snapshot['scripts'].find { |s| s['name'] == 'gempy_control' }['state']
    bridge.running = false
    bridge.error = 'crash'
    refute barrier.snapshot['ready'], 'a failed bridge must not certify startup'
  end

  def test_child_registered_during_snapshot_prevents_premature_ready
    barrier = GempyCheckinOwnership::StartupBarrier.new(required: ['parent'], background: [])
    child = ScriptResult.new('child', true, false)
    parent = ScriptResult.new('parent', false, true)
    parent.define_singleton_method(:running?) { barrier.record(child); false }
    barrier.record(parent)
    refute barrier.snapshot['ready']
  end

  def test_missing_and_failed_scripts_do_not_pass
    barrier = GempyCheckinOwnership::StartupBarrier.new(required: %w[autostart finite], background: [])
    barrier.record(ScriptResult.new('autostart', false, true))
    refute barrier.snapshot['ready']
    barrier.record(ScriptResult.new('finite', false, true, 'crash'))
    refute barrier.snapshot['ready']
  end
end

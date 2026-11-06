# frozen_string_literal: true

# Loaded with ruby -r BEFORE Lich initializes or accepts a frontend. This hook
# applies only to a tagged check-in launch; ordinary Lich launches are unchanged.
require 'json'
require 'socket'
require 'timeout'

module GempyCheckinOwnership
  class StartupBarrier
    def initialize(required:, background:)
      @required = required
      # Gempy's command bridge is a persistent listener, not finite login work.
      # Keep it optional for accounts without the bridge in their autostart list.
      @background = background | %w[gempy_control]
      @scripts = []
      @mutex = Mutex.new
    end

    def record(script)
      @mutex.synchronize { @scripts << script unless @scripts.include?(script) }
    end

    def snapshot
      scripts = @mutex.synchronize { @scripts.dup }
      states = scripts.map do |script|
        background = @background.include?(script.name)
        complete = !script.running? && script.completed_successfully?
        { 'name' => script.name, 'state' => complete ? 'complete' :
          (background && script.running? ? 'background' : script.running? ? 'running' : 'failed') }
      end
      names = states.map { |row| row['name'] }
      unchanged = @mutex.synchronize { @scripts == scripts }
      { 'ready' => unchanged && !@required.empty? && (@required - names).empty? &&
          states.all? { |row| %w[complete background].include?(row['state']) }, 'scripts' => states }
    rescue StandardError
      { 'ready' => false, 'scripts' => [] }
    end
  end

  class Arbiter
    def initialize(capture_id:, attached:, ready:, logout:)
      @capture_id, @attached, @ready, @logout = capture_id, attached, ready, logout
      @mutex = Mutex.new
      @state = 'owned'
    end

    def register
      @mutex.synchronize do
        return false if @state == 'logging_out'
        @state = 'user_owned' # Permanent even if the frontend later disconnects.
        yield
        true
      end
    end

    def command(action, capture_id)
      exit_now = false
      result = @mutex.synchronize do
        next({ 'state' => 'denied' }) unless capture_id == @capture_id
        next({ 'state' => 'unavailable' }) unless @ready.call
        case action
        when 'takeover'
          @state = 'user_owned' unless @state == 'logging_out'
        when 'logout'
          if @state == 'owned'
            begin
              clients = @attached.call
              @state = clients.is_a?(Array) ? (clients.empty? ? 'logging_out' : 'user_owned') : 'uncertain'
            rescue StandardError
              @state = 'uncertain'
            end
            exit_now = @state == 'logging_out'
          end
        when 'status'
          # Read-only capability and ownership probe.
        else
          next({ 'state' => 'denied' })
        end
        { 'state' => @state }
      end
      # Registration is already fenced. Do not hold the mutex across script
      # teardown: hooks can request takeover and must receive "too late".
      yield result if block_given?
      @logout.call if exit_now
      result
    end
  end

  module Registration
    private

    def detachable_client_register(client)
      return super unless GempyCheckinOwnership.guard
      accepted = GempyCheckinOwnership.guard.register { super }
      unless accepted
        client.close rescue nil
        raise IOError, 'Daily Check-in logout already began; attachment refused'
      end
      client
    end

    def gempy_checkin_takeover!
      GempyCheckinOwnership.guard&.command('takeover', GempyCheckinOwnership.capture_id)
    end
  end

  class << self
    attr_reader :guard, :capture_id, :startup

    def process_start
      File.read('/proc/self/stat').split(') ', 2).last.split[19].to_i
    end

    def ready?
      Object.ancestors.include?(Registration) &&
        defined?($_DETACHABLE_CLIENT_REGISTRY_) &&
        defined?(Lich::Common::OrderlyShutdown) &&
        defined?(Lich::Common::ShutdownCoordinator) &&
        Object.private_method_defined?(:detachable_clients_snapshot)
    end

    def install(context)
      @capture_id = context.fetch('capture_id')
      @startup = StartupBarrier.new(required: Array(context['startup_required']),
        background: Array(context['startup_background']))
      # Observe actual script objects before autostart. ExecScript/SubScript
      # initialize separately, so a return trace covers those child paths too.
      @startup_trace = TracePoint.new(:return) do |trace|
        if trace.method_id == :initialize && trace.path.end_with?('/common/script.rb') &&
            defined?(Lich::Common::Script) && trace.self.is_a?(Lich::Common::Script)
          @startup.record(trace.self)
        end
      end
      @startup_trace.enable if context['startup_mode'] == 'tracked'
      raise 'Invalid check-in attempt' unless @capture_id.match?(/\A[a-f0-9]{48}\z/)
      path = context.fetch('control_socket')
      raise 'Unsafe control directory' unless File.stat(File.dirname(path)).uid == Process.uid &&
        (File.stat(File.dirname(path)).mode & 0o077).zero?
      server = UNIXServer.new(path) # Never replace an existing socket.
      File.chmod(0o600, path)
      @guard = Arbiter.new(capture_id: @capture_id,
        attached: -> { Object.new.send(:detachable_clients_snapshot) },
        ready: -> { ready? },
        logout: -> {
          Lich::Common::OrderlyShutdown.request_user_exit(
            source: :gempy_checkin, server_exit_command: "#{$cmd_prefix}exit",
            active_sessions_lifecycle: Lich::InternalAPI::ActiveSessions::Lifecycle)
        })
      Object.prepend(Registration)
      at_exit { server.close rescue nil; File.unlink(path) rescue nil }
      Thread.new do
        loop do
          begin
            client = server.accept
          rescue IOError, Errno::EBADF
            break if server.closed?
            raise
          end
          begin
            request = nil
            Timeout.timeout(3) do
              raw = client.gets(4097)
              raise 'Invalid control request' unless raw && raw.bytesize <= 4096 && raw.end_with?("\n")
              request = JSON.parse(raw)
              identity = request['pid'] == Process.pid && request['process_start'] == process_start
              # Logout may drain scripts for up to Lich's bounded shutdown limit.
              # Dispatch after leaving the short request-read timeout.
              request = nil unless identity
            end
            send_reply = lambda do |reply|
              client.puts JSON.generate(reply.merge('pid' => Process.pid, 'process_start' => process_start,
                'capture_id' => @capture_id, 'protocol' => 1, 'startup' => @startup.snapshot))
              client.flush
            end
            if request
              @guard.command(request['action'], request['capture_id'], &send_reply)
            else
              send_reply.call('state' => 'denied')
            end
          rescue StandardError
            # No fallback command or speculative logout on control errors.
          ensure
            client.close rescue nil
          end
        end
      end
    end
  end
end

if ENV['GEMPY_CHECKIN_CONTEXT']
  GempyCheckinOwnership.install(JSON.parse(ENV.fetch('GEMPY_CHECKIN_CONTEXT')))
end

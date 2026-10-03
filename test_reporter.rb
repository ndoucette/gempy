require 'ostruct'
CharSettings = {}
def no_kill_all; end
def no_pause_all; end
def hide_me; end
def silence_me; end
source = File.read(File.join(__dir__, 'scripts/gempy_reporter.lic')).sub(/GempyReporter.main\s*\z/, '')
eval(source, TOPLEVEL_BINDING, 'gempy_reporter.lic')
def assert(value, message)
  raise message unless value
end
xml = %q{<dialogData id='expr'><progressBar exp='1000000' ascension_exp='30000' field_exp='500' max_field_exp='1000' until_next='1500' fashlonae='2'/></dialogData>}
assert(GempyReporter.observe(xml) == xml, 'Traffic must pass through unchanged')
exp = GempyReporter.instance_variable_get(:@experience)
assert(exp[:lifetime_exp] == 1000000 && exp[:ascension_exp] == 30000, 'Native counters')
GempyReporter.observe(xml.sub("exp='1000000'", "exp='1000100'").sub("ascension_exp='30000'", "ascension_exp='30025'"))
assert(GempyReporter.instance_variable_get(:@last_pulse) == 125, 'Native pulse')
GempyReporter.observe('Experience: 1,001,000 Field Exp: 500/1000')
assert(GempyReporter.instance_variable_get(:@last_pulse) == 125, 'Command output must not be counted as pulse')
GempyReporter.observe('Exp to next TP: 1,000 Exp to next ATP: 20,000')
GempyReporter.observe('PTPs/MTPs: 12/34 ATPs: 56')
assert(exp[:exp_to_next_tp] == 1000 && exp[:exp_to_next_atp] == 20000 && exp[:total_atps] == 56, 'Training points')
GempyReporter.observe('You have 5,713 points of doubled experience remaining. It is scheduled to refresh in 5 days, 3 hours, 12 minutes.')
bonus = GempyReporter.instance_variable_get(:@bonuses)
assert(bonus[:lumnis_stage] == 2 && bonus[:lumnis_points_remaining] == 5713, 'Lumnis stage')
assert((bonus[:lumnis_reset_at] - Time.now.to_i - (5*86400+3*3600+12*60)).abs < 2, 'Lumnis reset')
assert(bonus[:fashlonae_state] == 'active', 'Fash native state')
GempyReporter.observe('Your Gift of Lumnis has expired for this week.')
assert(bonus[:lumnis_stage] == 'expired', 'Lumnis expired')
GempyReporter.observe('You have not made any recent donations to the Temple of Lumnis.')
assert(bonus[:lumnis_donations] == 0, 'Known zero donations')
Char = OpenStruct.new(name: 'Example', health: 20, max_health: 100, percent_health: 20,
                      mana: 0, max_mana: 100, percent_mana: 0, stamina: 50,
                      max_stamina: 100, percent_stamina: 50, spirit: 10, max_spirit: 10, percent_spirit: 100)
Stats = OpenStruct.new(level: 100, prof: 'Wizard', exp: 1_001_000)
Experience = OpenStruct.new(fxp_current: 500, fxp_max: 1000, axp: 30_025)
XMLData = OpenStruct.new(game: 'GSIV', next_level_text: nil, next_level_value: 100)
Room = OpenStruct.new(current: nil)
UserVars = OpenStruct.new
snapshot = GempyReporter.collect
assert(snapshot[:character][:name] == 'Example', 'Capped character still reports')
assert(snapshot[:location].nil?, 'Unavailable room is null')
assert(snapshot[:vitals][:mana][:current] == 0, 'Known zero remains zero')
assert(snapshot[:resources][:weekly].nil?, 'Missing resource remains unavailable')
assert(snapshot[:metadata][:availability]['resources'][:available] == false, 'Unknown resource availability')
assert(snapshot[:experience][:lifetime_exp] == 1_001_000, 'Lifetime cache collected')
assert(snapshot[:experience][:ascension_exp] == 30_025, 'Ascension cache collected')
assert(snapshot[:process_start].is_a?(Integer), 'Linux process start included') if File.exist?('/proc/self/stat')
JSON.generate(snapshot)
puts 'Reporter parser and capped/null collection checks passed'

module Lich
  module Util; end
end
module Lich::Util
  def self.quiet_command_xml(command, start, finish, include_end, timeout)
    raise 'Missing report start boundary' unless start.match?('<output class="mono"/>')
    raise 'Missing prompt boundary' unless finish.match?('<prompt time="1">')
    raise 'Unbounded capture' unless timeout == 5 && include_end
    ['Experience: 1,002,000 Field Exp: 500/1000']
  end
end
GempyReporter.refresh_command('experience')
assert(exp[:lifetime_exp] == 1_002_000, 'Quiet report still updates experience')
GempyReporter.refresh_command('lumnis info')
GempyReporter.refresh_command('resource')
puts 'Quiet command capture checks passed'

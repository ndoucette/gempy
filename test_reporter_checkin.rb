require_relative 'test_reporter'

# These tests evaluate parser methods with stubbed command output. No Lich runs.
GempyReporter.instance_variable_set(:@checkin_context, {'capture_id'=>'a'*48,'startup_mode'=>'ack'})
request={'checkin_request'=>{'capture_id'=>'a'*48,'requested_at'=>Time.now.to_i,'startup_mode'=>'ack'}}
GempyReporter.accept_checkin_response(request)
assert(GempyReporter.checkin_step == false, 'Explicit startup acknowledgment required')
GempyReporter.checkin_ready!
GempyReporter.accept_checkin_response({'checkin_request'=>{'capture_id'=>'b'*48}})
assert(GempyReporter.instance_variable_get(:@checkin_request)['capture_id']=='a'*48, 'Wrong capture ID ignored')

module Lich::Util
  class << self
    attr_accessor :fixture
    def quiet_command_xml(command, *args)
      fixture.is_a?(Hash) ? fixture.fetch(command, []) : fixture || []
    end
  end
end
Lich::Util.fixture=['<prompt time="1">']
7.times { GempyReporter.checkin_step }
receipt=GempyReporter.collect[:checkin]
assert(receipt[:phase]=='captured', 'Bounded capture terminates')
assert(receipt[:fields].values.none?{|field| field[:status]=='captured'}, 'Cached profile values do not count as captured')
assert(receipt[:fields]['bank'][:status]=='unavailable', 'No bank traversal or runner use')
assert(receipt[:startup_ready], 'Startup success explicit')

GempyReporter.instance_variable_set(:@checkin_index,4)
GempyReporter.instance_variable_get(:@checkin_receipt)[:phase]='capturing'
Lich::Util.fixture=['Experience: 1,001,000 Field Exp: 500/1000','  Long-Term Exp: 4,000  Deeds: 17','<prompt time="2">']
GempyReporter.checkin_step
assert(GempyReporter.collect[:checkin][:fields]['deeds'][:status]=='captured', 'Deeds captured from EXPERIENCE, not INFO FULL')

# Complete synthetic command responses exercise the actual parsers. No game I/O.
stats=%w[Strength Constitution Dexterity Agility Discipline Aura Logic Intuition Wisdom Influence].zip(%w[STR CON DEX AGI DIS AUR LOG INT WIS INF]).map { |name,code| "  #{name} (#{code}): 80 (15) ... 80 (15)" }
Lich::Util.fixture={
  'info full'=>['Name: Example']+stats+['<prompt time="3">'],
  'skill'=>[' Example (at level 100), your current skill bonuses and ranks are:','  Arcane Symbols.....................| 90 20','Training Points: 0 Phy 0 Mnt','<prompt time="3">'],
  'lumnis info'=>['Your Gift of Lumnis has expired for this week.','<prompt time="3">'],
  'resource'=>['Essence: 1/50,000 (Weekly)  5/200,000 (Total)','<prompt time="3">'],
  'experience'=>['Experience: 1,001,000 Field Exp: 500/1000','  Long-Term Exp: 4,000  Deeds: 17','<prompt time="3">'],
  'boost info'=>['Current Login Streak: 12 days','<prompt time="3">']
}
GempyReporter.instance_variable_set(:@checkin_request,nil)
GempyReporter.accept_checkin_response(request)
7.times { GempyReporter.checkin_step }
snapshot=GempyReporter.collect
%w[character stats skills bonuses resources experience deeds reward_info].each do |field|
  assert(snapshot[:checkin][:fields][field][:status]=='captured', "Fresh #{field} response captured")
end
assert(snapshot[:stats].size==10 && snapshot[:wealth][:deeds]==17, 'Parsed values accompany the receipt')

GempyReporter.observe('Current Login Streak:           30 days')
assert(GempyReporter.collect[:login_rewards][:streak]==30, 'Day 30 observed')
GempyReporter.observe('Current Login Streak:           1 days')
assert(GempyReporter.collect[:login_rewards][:streak]==1, 'Normal reward-cycle wrap accepted')
GempyReporter.instance_variable_set(:@checkin_context,nil)
GempyReporter.instance_variable_set(:@checkin_request,nil)
GempyReporter.accept_checkin_response(request)
assert(GempyReporter.instance_variable_get(:@checkin_request).nil?, 'Existing user sessions ignore automation requests')
puts 'Check-in reporter isolation, freshness, startup and reward checks passed'

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

# BANK ACCOUNT is a read-only balance query, independent of bank.lic or room tags.
Room.current = nil
XMLData.room_title = '[Safe Haven, Great Room]'
Lich::Util.fixture = { 'bank account' => [
  'You currently have the following amounts on deposit:',
  '  Wehnimer\'s Landing: 1,234',
  '  Total: 1,234',
  '<prompt time="4">'
] }
GempyReporter.instance_variable_set(:@checkin_context, {'capture_id'=>'a'*48,'startup_mode'=>'ack'})
GempyReporter.instance_variable_set(:@checkin_request,nil)
GempyReporter.accept_checkin_response(request)
GempyReporter.instance_variable_set(:@checkin_index,6)
GempyReporter.checkin_step
bank_receipt=GempyReporter.collect
assert(bank_receipt[:checkin][:fields]['bank'][:status]=='captured', 'BANK ACCOUNT must be sent outside bank-tagged rooms')
assert(bank_receipt[:wealth][:bank_balance]==1234, 'Fresh bank total must accompany the capture')
puts 'Remote read-only BANK ACCOUNT capture passed'

# Liviloo's RESOURCE output contains vitals only before profession resources unlock.
vitals = 'Health: 152/152     Mana: 131/131     Stamina: 66/66     Spirit: 8/9'
def capture_resources(lines)
  Lich::Util.fixture = {'resource' => lines}
  GempyReporter.instance_variable_set(:@checkin_index, 3)
  GempyReporter.instance_variable_get(:@checkin_receipt)[:phase] = 'capturing'
  GempyReporter.checkin_step
  GempyReporter.collect
end
empty = capture_resources([vitals, '<prompt time="5">'])
assert(empty[:checkin][:fields]['resources'][:status] == 'captured', 'Completed vitals-only RESOURCE response counts as captured')
assert(empty[:resources].values_at(:weekly, :total, :suffused) == [0, 0, 0], 'No profession resources means known zero, replacing old values')
assert(empty[:resources][:observed_at] == empty[:checkin][:fields]['resources'][:observed_at], 'Zero resources have a fresh observation')
gringott = capture_resources(['Health: 40/40     Mana: 0/0     Stamina: 59/59     Spirit: 7/7', '<prompt time="5">'])
assert(gringott[:checkin][:fields]['resources'][:status] == 'captured' && gringott[:resources][:total] == 0, 'Gringott zero-mana vitals-only report is also captured as zero')
[[], ['<prompt time="6">'], [vitals], [vitals, 'Essence: unreadable (Weekly)', '<prompt time="6">']].each do |lines|
  result = capture_resources(lines)
  assert(result[:checkin][:fields]['resources'][:status] == 'unavailable', 'Missing, truncated or malformed resource output must not count as zero')
end
puts 'Empty profession resources and incomplete-response checks passed'

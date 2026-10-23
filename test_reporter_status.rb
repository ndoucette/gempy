require_relative 'test_reporter'

GempyReporter.observe('Essence: 12,345/50,000 (Weekly)  120,000/200,000 (Total)')
GempyReporter.observe('Suffused Essence: 1,234')
GempyReporter.observe('  Long-Term Exp: 4,000  Deeds: 17')
data = GempyReporter.collect
assert(data.dig(:resources, :suffused) == 1234, 'Suffused resource captured')
assert(data.dig(:wealth, :deeds) == 17, 'Deeds captured from experience')
suffused_time = data.dig(:resources, :suffused_observed_at)
GempyReporter.observe('Essence: 15,000/50,000 (Weekly)  121,000/200,000 (Total)')
assert(GempyReporter.collect.dig(:resources, :suffused) == 1234, 'Resource refresh preserves last suffused')
assert(GempyReporter.collect.dig(:resources, :suffused_observed_at) == suffused_time, 'Independent suffused observation')
GempyReporter.observe('  Total: 999,999')
assert(GempyReporter.collect.dig(:wealth, :bank_balance).nil?, 'Unrelated totals ignored')
GempyReporter.observe('You currently have the following amounts on deposit:')
GempyReporter.observe('  Wehnimer\'s Landing Bank: 123,000')
GempyReporter.observe('  Total: 123,000')
assert(GempyReporter.collect.dig(:wealth, :bank_balance).nil?, 'Partial bank report not committed')
GempyReporter.observe('<prompt time="1">')
assert(GempyReporter.collect.dig(:wealth, :bank_balance) == 123000, 'Completed all-bank total committed')
bank_time = GempyReporter.collect.dig(:wealth, :bank_balance_observed_at)
GempyReporter.observe('You currently have the following amounts on deposit:')
GempyReporter.observe('  Wehnimer\'s Landing Bank: 1')
GempyReporter.observe('<prompt time="2">')
GempyReporter.observe("You don't have access to a bank here.")
assert(GempyReporter.collect.dig(:wealth, :bank_balance) == 123000, 'Partial or denied bank queries preserve balance')
assert(GempyReporter.collect.dig(:wealth, :bank_balance_observed_at) == bank_time, 'Unchanged balance keeps observation time')
GempyReporter.observe('You currently have the following amounts on deposit:')
GempyReporter.observe('  Total: 0')
GempyReporter.observe('<prompt time="3">')
GempyReporter.observe('Suffused Essence: 0')
GempyReporter.observe('  Long-Term Exp: 0  Deeds: 0')
data = GempyReporter.collect
assert(data.dig(:resources, :suffused) == 0 && data.dig(:wealth, :deeds) == 0 && data.dig(:wealth, :bank_balance) == 0, 'Known zero preserved')
module Lich::Util
  def self.quiet_command_xml(*)
    raise 'Must not query a remote bank'
  end
end
GempyReporter.refresh_command('bank account')
puts 'Status reporter checks passed'

// Independent two-half subset enumerator. Inputs are raw public primitives.
// No project cash flows or finance results are accepted from another kernel.
#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

using I = std::int64_t;
using W = __int128_t;
static constexpr I SCALE = 1000000000000LL;
static constexpr int NY = 20, NS = 3, NF = 8;
using Series = std::array<I, NY>;
using YearFlow = std::array<I, NF>;
using PortfolioFlow = std::array<std::array<YearFlow, NY>, NS>;
enum Field { Revenue, Expense, Outlay, Depreciation, Sale, Gain, Book, NAV };

static I integer(W value) {
    if (value < std::numeric_limits<I>::min() || value > std::numeric_limits<I>::max())
        throw std::runtime_error("B financial integer overflow");
    return static_cast<I>(value);
}

static I post(W numerator, W denominator = SCALE) {
    if (denominator <= 0) throw std::runtime_error("Invalid B posting denominator");
    W magnitude = numerator < 0 ? -numerator : numerator;
    W nearest = (magnitude * 2 + denominator) / (denominator * 2);
    return integer(numerator < 0 ? -nearest : nearest);
}

struct Project {
    int commission, sale_year, life;
    I cost, sale_price;
    Series revenue{}, expense{};
};

struct Scenario {
    Series sales{}, costs{}, valuation{}, exit_price{}, interest{}, haircut{};
};

struct Public {
    int count, dimensions, carry;
    std::vector<int> active;
    I opening, minimum, commitment, facility, advance, tax;
    Series discount{};
    std::vector<Project> projects;
    std::array<Scenario, NS> scenarios;
};

static I number(std::istream& input) {
    I value;
    if (!(input >> value)) throw std::runtime_error("Truncated B raw primitive wire");
    return value;
}

static Series series(std::istream& input) {
    Series values{};
    for (I& value : values) value = number(input);
    return values;
}

static Public read_public(std::istream& input) {
    std::string marker;
    input >> marker;
    if (marker != "CAPITAL_TWO_HALF_B_RAW_V1") throw std::runtime_error("Wrong B raw wire identity");
    Public p{};
    p.count = static_cast<int>(number(input));
    p.dimensions = static_cast<int>(number(input));
    if ((p.count != 18 && p.count != 26 && p.count != 28 && p.count != 30)
            || p.dimensions < 1 || p.dimensions > p.count) throw std::runtime_error("Wrong B dimension");
    std::vector<bool> used(p.count, false);
    for (int k = 0; k < p.dimensions; ++k) {
        int index = static_cast<int>(number(input));
        if (index < 0 || index >= p.count || used[index]) throw std::runtime_error("Invalid B active project map");
        used[index] = true; p.active.push_back(index);
    }
    p.opening = number(input); p.minimum = number(input); p.commitment = number(input);
    p.facility = number(input); p.advance = number(input); p.tax = number(input);
    p.carry = static_cast<int>(number(input));
    if (p.carry < 1 || p.carry > 20) throw std::runtime_error("Wrong B loss carry window");
    p.discount = series(input);
    for (int index = 0; index < p.count; ++index) {
        Project project{};
        project.commission = static_cast<int>(number(input));
        project.sale_year = static_cast<int>(number(input));
        project.cost = number(input); project.life = static_cast<int>(number(input));
        project.sale_price = number(input);
        project.revenue = series(input); project.expense = series(input);
        if (project.commission < 0 || project.sale_year >= NY || project.commission >= project.sale_year
                || project.life < 1 || project.life > 20) throw std::runtime_error("Wrong B raw project dates");
        p.projects.push_back(project);
    }
    for (auto& scenario : p.scenarios) {
        scenario.sales = series(input); scenario.costs = series(input); scenario.valuation = series(input);
        scenario.exit_price = series(input); scenario.interest = series(input); scenario.haircut = series(input);
    }
    std::string extra;
    if (input >> extra) throw std::runtime_error("Unexpected extra B raw primitive wire data");
    return p;
}

static PortfolioFlow project_flows(const Public& p, int index) {
    const Project& project = p.projects[index];
    PortfolioFlow result{};
    for (int s = 0; s < NS; ++s) {
        const Scenario& scenario = p.scenarios[s];
        I remaining = 0;
        for (int y = 0; y < NY; ++y) {
            auto& f = result[s][y];
            if (y == project.commission) { remaining += project.cost; f[Outlay] = project.cost; }
            int age = y - project.commission;
            if (age > 0 && y <= project.sale_year) {
                f[Revenue] = post(W(project.revenue[y]) * scenario.sales[y]);
                f[Expense] = post(W(project.expense[y]) * scenario.costs[y]);
                if (age <= project.life) {
                    I scheduled = age == project.life ? remaining : post(project.cost, project.life);
                    f[Depreciation] = std::min(remaining, std::max<I>(0, scheduled));
                    remaining -= f[Depreciation];
                }
            }
            if (y == project.sale_year) {
                f[Sale] = post(W(project.sale_price) * scenario.exit_price[y]);
                f[Gain] = f[Sale] - remaining;
                remaining = 0;
            }
            f[Book] = remaining;
            f[NAV] = post(W(remaining) * scenario.valuation[y]);
        }
    }
    return result;
}

// Ordinal subset DP adds the highest set bit, independently of A's Gray walk.
static std::vector<PortfolioFlow> half_table(const std::vector<PortfolioFlow>& projects, int begin, int size) {
    std::vector<PortfolioFlow> table(std::uint32_t(1) << size);
    for (std::uint32_t mask = 1; mask < table.size(); ++mask) {
        int bit = 31 - __builtin_clz(mask);
        std::uint32_t parent = mask ^ (std::uint32_t(1) << bit);
        for (int s = 0; s < NS; ++s) for (int y = 0; y < NY; ++y) for (int f = 0; f < NF; ++f)
            table[mask][s][y][f] = table[parent][s][y][f] + projects[begin + bit][s][y][f];
    }
    return table;
}

struct Outcome { bool feasible; I npv; };

static Outcome close(const Public& p, int scenario, const PortfolioFlow& low, const PortfolioFlow& high,
                     std::uint64_t& years_evaluated) {
    const Scenario& terms = p.scenarios[scenario];
    I cash = p.opening, capital = p.opening, retained = 0, debt = 0, calls = 0, certified = 0;
    std::array<I, NY> losses{};
    W discounted = -W(p.opening) * SCALE;
    for (int y = 0; y < NY; ++y) {
        ++years_evaluated;
        YearFlow flow{};
        for (int field = 0; field < NF; ++field) flow[field] = low[scenario][y][field] + high[scenario][y][field];
        I interest = post(W(debt) * terms.interest[y]);
        I profit = flow[Revenue] + flow[Gain] - flow[Expense] - flow[Depreciation] - interest;
        int expires = y - p.carry - 1;
        if (expires >= 0) losses[expires] = 0;
        I taxable = std::max<I>(0, profit);
        for (int vintage = std::max(0, y - p.carry); vintage < y && taxable; ++vintage) {
            I utilised = std::min(taxable, losses[vintage]);
            taxable -= utilised; losses[vintage] -= utilised;
        }
        losses[y] = std::max<I>(0, -profit);
        I tax = post(W(taxable) * p.tax), income = profit - tax;
        I base = y == NY - 1 ? 0 : std::min(p.facility,
            post(W(certified) * p.advance * (SCALE - terms.haircut[y]), W(SCALE) * SCALE));
        I floor = y == NY - 1 ? 0 : p.minimum;
        cash += flow[Revenue] - flow[Expense] - flow[Outlay] + flow[Sale] - interest - tax;
        I mandatory = std::max<I>(0, debt - base);
        debt -= mandatory; cash -= mandatory;
        I optional = std::min(debt, std::max<I>(0, cash - floor));
        debt -= optional; cash -= optional;
        I drawn = std::min(std::max<I>(0, base - debt), std::max<I>(0, floor - cash));
        debt += drawn; cash += drawn;
        I required = std::max<I>(0, floor - cash), call = std::min(required, p.commitment - calls);
        cash += call; calls += call;
        I equity = capital + call + retained + income;
        I distribution = std::min(std::max<I>(0, cash - floor), std::max<I>(0, equity));
        I returned = std::min(distribution, capital + call);
        capital += call - returned; retained += income - (distribution - returned); cash -= distribution;
        if (W(cash) + flow[Book] != W(debt) + capital + retained)
            throw std::runtime_error("B independent legal balance invariant failed");
        // A null outcome does not claim the unevaluated future years were run.
        if (required > call) return {false, std::numeric_limits<I>::min()};
        certified = flow[NAV];
        discounted += W(distribution - call) * p.discount[y];
        if (y == NY - 1 && (cash || debt || flow[Book])) return {false, std::numeric_limits<I>::min()};
    }
    I npv = post(discounted);
    if (npv == std::numeric_limits<I>::min()) throw std::runtime_error("B feasible NPV collides with protocol null sentinel");
    return {true, npv};
}

static void u32(std::vector<char>& buffer, std::uint32_t value) {
    for (int shift = 0; shift < 32; shift += 8) buffer.push_back(static_cast<char>((value >> shift) & 255));
}
static void i64(std::vector<char>& buffer, I value) {
    auto bits = static_cast<std::uint64_t>(value);
    for (int shift = 0; shift < 64; shift += 8) buffer.push_back(static_cast<char>((bits >> shift) & 255));
}

int main(int argc, char** argv) {
    try {
        if (argc != 3) throw std::runtime_error("B expects raw primitive wire and output records paths");
        std::ifstream input(argv[1]);
        if (!input) throw std::runtime_error("Cannot read B raw primitives");
        Public p = read_public(input);
        std::vector<PortfolioFlow> flows;
        for (int index : p.active) flows.push_back(project_flows(p, index));
        int low_bits = p.dimensions / 2;
        auto low = half_table(flows, 0, low_bits);
        auto high = half_table(flows, low_bits, p.dimensions - low_bits);
        std::ofstream output(argv[2], std::ios::binary | std::ios::trunc);
        if (!output) throw std::runtime_error("Cannot write B records");
        std::vector<char> buffer; buffer.reserve(65536 * 32);
        std::uint64_t feasible_count = 0, year_count = 0, plan_count = std::uint64_t(1) << p.dimensions;
        for (std::uint32_t upper = 0; upper < high.size(); ++upper) {
            for (std::uint32_t lower = 0; lower < low.size(); ++lower) {
                std::uint32_t mask = (upper << low_bits) | lower, flags = 0;
                std::array<Outcome, NS> result{};
                for (int s = 0; s < NS; ++s) {
                    result[s] = close(p, s, low[lower], high[upper], year_count);
                    if (result[s].feasible) flags |= std::uint32_t(1) << s;
                }
                if (flags == 7) ++feasible_count;
                u32(buffer, mask); u32(buffer, flags);
                for (const auto& scenario : result) i64(buffer, scenario.npv);
                if (buffer.size() == 65536 * 32) { output.write(buffer.data(), buffer.size()); buffer.clear(); }
            }
        }
        if (!buffer.empty()) output.write(buffer.data(), buffer.size());
        output.flush();
        if (!output) throw std::runtime_error("B output record write failed");
        std::cout << "{\"plan_count\":" << plan_count << ",\"feasible_count\":" << feasible_count
                  << ",\"scenario_evaluations\":" << plan_count * NS << ",\"scenario_year_evaluations\":" << year_count
                  << ",\"subset_table_bytes\":" << (low.size() + high.size()) * sizeof(PortfolioFlow)
                  << ",\"method\":\"independent_two_half_ordinal_subset_tables\"}\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 2; }
}

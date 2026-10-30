// Independent integer-pence evaluator.  The input contains raw public primitives,
// never a forward ledger, project NPV, financing plan, or Python-computed flow.
#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using I = std::int64_t;
using W = __int128_t;
constexpr I SCALE = 1000000000000LL;
constexpr int NY = 20, NP = 18, NS = 3, NF = 55;

static I narrow(W value) {
    if (value < std::numeric_limits<I>::min() || value > std::numeric_limits<I>::max())
        throw std::runtime_error("Integer amount exceeds signed 64-bit storage");
    return static_cast<I>(value);
}
static I rounded(W numerator, W denominator) {
    if (denominator <= 0) throw std::runtime_error("Invalid rounding denominator");
    bool negative = numerator < 0;
    W amount = negative ? -numerator : numerator;
    W answer = amount / denominator;
    if (2 * (amount % denominator) >= denominator) ++answer;
    return narrow(negative ? -answer : answer);
}
static I positive(I value) { return std::max<I>(0, value); }

// SHA-256 is implemented here to retain a portable, self-contained C++ proof.
// Each path is encoded explicitly as signed 64-bit little-endian integers.
class Sha256 {
    std::array<std::uint32_t, 8> state{{
        0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
        0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}};
    std::array<unsigned char, 64> block{};
    std::uint64_t length = 0;
    std::size_t used = 0;
    static std::uint32_t rr(std::uint32_t x, int n) { return (x >> n) | (x << (32-n)); }
    void transform() {
        static constexpr std::uint32_t k[64] = {
            0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
            0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
            0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
            0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
            0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
            0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
            0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
            0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
        std::uint32_t w[64];
        for (int n=0;n<16;++n) w[n] = (std::uint32_t(block[n*4])<<24) |
            (std::uint32_t(block[n*4+1])<<16) | (std::uint32_t(block[n*4+2])<<8) | block[n*4+3];
        for (int n=16;n<64;++n) {
            auto s0 = rr(w[n-15],7)^rr(w[n-15],18)^(w[n-15]>>3);
            auto s1 = rr(w[n-2],17)^rr(w[n-2],19)^(w[n-2]>>10);
            w[n] = w[n-16]+s0+w[n-7]+s1;
        }
        auto a=state[0],b=state[1],c=state[2],d=state[3];
        auto e=state[4],f=state[5],g=state[6],h=state[7];
        for (int n=0;n<64;++n) {
            auto t1=h+(rr(e,6)^rr(e,11)^rr(e,25))+((e&f)^((~e)&g))+k[n]+w[n];
            auto t2=(rr(a,2)^rr(a,13)^rr(a,22))+((a&b)^(a&c)^(b&c));
            h=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
        }
        state[0]+=a;state[1]+=b;state[2]+=c;state[3]+=d;
        state[4]+=e;state[5]+=f;state[6]+=g;state[7]+=h;
    }
    void byte(unsigned char value) {
        block[used++]=value;
        if (used==64) { transform(); used=0; }
    }
public:
    void integer(I value) {
        std::uint64_t bits = static_cast<std::uint64_t>(value);
        for (int n=0;n<8;++n) byte(static_cast<unsigned char>((bits>>(n*8))&255));
        length+=8;
    }
    std::string finish() {
        const auto bitlength=length*8;
        byte(0x80);
        while (used!=56) byte(0);
        for (int n=7;n>=0;--n) byte(static_cast<unsigned char>((bitlength>>(n*8))&255));
        std::ostringstream result;
        for (auto value:state) result<<std::hex<<std::setfill('0')<<std::setw(8)<<value;
        return result.str();
    }
};

struct Reader {
    std::ifstream input;
    explicit Reader(const char* path):input(path) {
        if (!input) throw std::runtime_error("Cannot open primitive input");
        std::string magic;
        std::getline(input,magic);
        if (magic!="CAPITAL_ALLOCATION_RAW_V1") throw std::runtime_error("Unsupported primitive format");
    }
    I number(I low,I high) {
        std::string token;
        if (!(input>>token)) throw std::runtime_error("Truncated primitive input");
        if (token.empty() || token.find_first_not_of("0123456789")!=std::string::npos)
            throw std::runtime_error("Primitive must be a nonnegative integer");
        W value=0;
        for (char ch:token) {
            value=value*10+(ch-'0');
            if (value>high) throw std::runtime_error("Primitive exceeds its declared bound");
        }
        if (value<low) throw std::runtime_error("Primitive is below its declared bound");
        return static_cast<I>(value);
    }
    void end() { std::string extra; if(input>>extra) throw std::runtime_error("Extra primitive input"); }
};
using Year = std::array<I, NY>;
struct Project { int commission,sale,life; I cost,price; Year revenue,opex; };
struct Scenario { Year revenue,opex,nav,sale,bank,haircut; };
struct Spec {
    std::vector<int> active;
    I cash,floor,commitment,facility,advance,tax;
    int carry;
    Year discount;
    std::array<Project,NP> projects;
    std::array<Scenario,NS> scenarios;
};
static Year years(Reader& r,I low,I high) {
    Year result{};
    for (auto& value:result) value=r.number(low,high);
    return result;
}
static Spec read(const char* path) {
    Reader r(path);
    if (r.number(NP,NP)!=NP || r.number(NS,NS)!=NS || r.number(NY,NY)!=NY)
        throw std::runtime_error("Unsupported dimensions");
    Spec s;
    int count=r.number(1,NP), previous=-1;
    for(int n=0;n<count;++n) {
        int p=r.number(0,NP-1);
        if(p<=previous) throw std::runtime_error("Active projects must retain public order");
        s.active.push_back(p);previous=p;
    }
    s.cash=r.number(0,100000000000LL);s.floor=r.number(0,s.cash);
    s.commitment=r.number(0,100000000000LL);s.facility=r.number(0,100000000000LL);
    s.advance=r.number(0,SCALE);s.tax=r.number(0,SCALE);s.carry=r.number(1,NY);
    s.discount=years(r,1,SCALE);
    for(int y=1;y<NY;++y) if(s.discount[y]>s.discount[y-1])
        throw std::runtime_error("Discount factors increase");
    for(auto& p:s.projects) {
        p.commission=r.number(0,NY-2);p.sale=r.number(p.commission+1,NY-1);
        p.cost=r.number(1,1000000000);p.life=r.number(1,NY);p.price=r.number(0,1000000000);
        p.revenue=years(r,0,1000000000);p.opex=years(r,0,1000000000);
        for(int y=0;y<NY;++y) if((y<=p.commission||y>p.sale) && (p.revenue[y]||p.opex[y]))
            throw std::runtime_error("Operating primitive outside project life");
    }
    for(auto& c:s.scenarios) {
        c.revenue=years(r,0,3*SCALE);c.opex=years(r,0,3*SCALE);
        c.nav=years(r,0,3*SCALE);c.sale=years(r,0,3*SCALE);
        c.bank=years(r,0,SCALE);c.haircut=years(r,0,SCALE);
    }
    r.end();return s;
}

// Public PROJECT_FIELDS order, independently compiled from each raw project.
using Flows=std::array<I,9>;
using AnnualFlows=std::array<Flows,NY>;
using ScenarioFlows=std::array<AnnualFlows,NS>;
using Primitives=std::array<std::array<AnnualFlows,NP>,NS>;
static Primitives compile(const Spec& s) {
    Primitives output{};
    for(int c=0;c<NS;++c) for(int p=0;p<NP;++p) {
        const auto& project=s.projects[p];const auto& scenario=s.scenarios[c];
        I book=0,ordinary_depreciation=rounded(W(project.cost),W(project.life));
        for(int y=0;y<NY;++y) {
            auto& f=output[c][p][y];
            if(y==project.commission) { f[0]=project.cost;book=project.cost; }
            if(y>project.commission&&y<=project.sale) {
                f[1]=rounded(W(project.revenue[y])*W(scenario.revenue[y]),W(SCALE));
                f[2]=rounded(W(project.opex[y])*W(scenario.opex[y]),W(SCALE));
                int age=y-project.commission;
                f[3]=age<=project.life ? (age==project.life ? book : std::min(book,positive(ordinary_depreciation))) : 0;
                book-=f[3];
                if(y==project.sale) {
                    f[4]=rounded(W(project.price)*W(scenario.sale[y]),W(SCALE));
                    f[5]=book;f[6]=f[4]-book;book=0;
                }
            }
            f[7]=book;
            f[8]=rounded(W(book)*W(scenario.nav[y]),W(SCALE));
        }
    }
    return output;
}
struct Evaluation { bool feasible;I npv;int first,violations;std::string hash; };
static Evaluation evaluate(const Spec& s,const ScenarioFlows& aggregate,int c) {
    I cash=s.cash,bank=0,capital=s.cash,retained=0,called=0,prior_nav=0;
    Year losses{};
    W numerator=-W(s.cash)*W(SCALE);
    Sha256 hash;
    int violations=0,first=0;
    for(int y=0;y<NY;++y) {
        const auto& f=aggregate[c][y];
        I interest=rounded(W(bank)*W(s.scenarios[c].bank[y]),W(SCALE));
        I taxable=narrow(W(f[1])-f[2]-f[3]+f[6]-interest);
        I loss_open=0,expired=0,used=0,created=0;
        for(int v=0;v<NY;++v) loss_open+=losses[v];
        for(int v=0;v<y;++v) if(y-v>s.carry) {expired+=losses[v];losses[v]=0;}
        I remaining=positive(taxable);
        for(int v=0;v<y&&remaining;++v) {
            I consume=std::min(remaining,losses[v]);losses[v]-=consume;remaining-=consume;used+=consume;
        }
        if(taxable<0) {created=-taxable;losses[y]=created;}
        I loss_close=0;for(auto value:losses) loss_close+=value;
        I tax=rounded(W(remaining)*W(s.tax),W(SCALE));
        I income=taxable-tax;
        I base=y==NY-1 ? 0 : std::min(s.facility,
            rounded(W(prior_nav)*W(s.advance)*W(SCALE-s.scenarios[c].haircut[y]),W(SCALE)*W(SCALE)));
        I before=narrow(W(cash)+f[1]-f[2]-f[0]+f[4]-interest-tax);
        I margin=positive(bank-base),after_margin=before-margin;
        I floor=y==NY-1?0:s.floor;
        I optional=std::min(bank-margin,positive(after_margin-floor));
        I after_optional=after_margin-optional;
        I draw=std::min(positive(base-(bank-margin-optional)),positive(floor-after_optional));
        I required=positive(floor-after_optional-draw);
        I call=std::min(required,positive(s.commitment-called));
        I gap=required-call;
        I pre_distribution=after_optional+draw+call;
        I equity=capital+call+retained+income;
        I distribution=std::min(positive(pre_distribution-floor),positive(equity));
        I roc=std::min(distribution,capital+call),profit=distribution-roc;
        I net=distribution-call,called_close=called+call,cash_close=pre_distribution-distribution;
        I bank_close=bank-margin-optional+draw,capital_close=capital+call-roc;
        I retained_close=retained+income-profit,assets=cash_close+f[7],book_equity=capital_close+retained_close;
        std::array<I,NF> row{{
            cash,bank,capital,retained,called,prior_nav,f[1],f[2],f[0],f[3],f[4],f[5],f[6],interest,
            taxable,loss_open,expired,used,created,loss_close,remaining,tax,income,
            base,before,margin,after_margin,optional,after_optional,draw,required,call,gap,
            pre_distribution,equity,distribution,roc,profit,net,called_close,s.commitment-called_close,
            cash_close,bank_close,capital_close,retained_close,f[7],f[8],assets,bank_close,book_equity,
            assets-bank_close-book_equity,
            cash_close-(cash+f[1]-f[2]-f[0]+f[4]-interest-tax+draw+call-margin-optional-distribution),
            bank_close-(bank-margin-optional+draw),capital_close-(capital+call-roc),
            loss_close-(loss_open-expired-used+created)}};
        for(int index=NF-5;index<NF;++index) if(row[index]!=0)
            throw std::runtime_error("Financial reconciliation residual is nonzero");
        hash.integer(2024+y);for(auto value:row) hash.integer(value);
        for(auto value:losses) hash.integer(value);
        numerator+=W(net)*W(s.discount[y]);
        if(gap>0) {violations|=1;if(!first)first=2024+y;}
        if(y==NY-1) {
            if(bank_close!=0) violations|=2;
            if(f[7]!=0) violations|=4;
            if(cash_close!=0) violations|=8;
            if(violations&&!first) first=2024+y;
        }
        cash=cash_close;bank=bank_close;capital=capital_close;
        retained=retained_close;called=called_close;prior_nav=f[8];
    }
    return {violations==0,rounded(numerator,W(SCALE)),first,violations,hash.finish()};
}
struct Ranked { bool set=false;I value=0;std::uint32_t mask=0,full=0; };
static void nullable(std::ostream& out,bool set,I value) {if(set)out<<value;else out<<"null";}
int main(int argc,char** argv) {
    try {
        if(argc!=3) throw std::runtime_error("Usage: search raw_primitives.txt all_plans.csv");
        const auto s=read(argv[1]);const auto primitives=compile(s);
        std::ofstream out(argv[2],std::ios::binary);
        if(!out) throw std::runtime_error("Cannot create complete enumeration CSV");
        out<<"mask,full_mask";
        for(int c=1;c<=NS;++c) out<<",S0"<<c<<"_feasible,S0"<<c<<"_npv_pence,S0"<<c
            <<"_path_sha256,S0"<<c<<"_first_violation_year,S0"<<c<<"_violation_mask";
        out<<",feasible,objective_pence\n";
        ScenarioFlows aggregate{};
        const std::uint32_t count=1U<<s.active.size();
        Ranked best,runner;I feasible_count=0,best_count=0;
        std::uint32_t full=0;
        for(std::uint32_t mask=0;mask<count;++mask) {
            if(mask) {
                auto changes=mask^(mask-1);
                for(std::size_t bit=0;bit<s.active.size();++bit) if(changes&(1U<<bit)) {
                    int p=s.active[bit],sign=(mask&(1U<<bit))?1:-1;
                    if(sign==1) full|=1U<<p;else full&=~(1U<<p);
                    for(int c=0;c<NS;++c) for(int y=0;y<NY;++y) for(int field=0;field<9;++field)
                        aggregate[c][y][field]+=sign*primitives[c][p][y][field];
                }
            }
            out<<mask<<','<<full;
            bool feasible=true;I objective=std::numeric_limits<I>::max();
            for(int c=0;c<NS;++c) {
                const auto result=evaluate(s,aggregate,c);
                out<<','<<(result.feasible?1:0)<<',';
                if(result.feasible) out<<result.npv;
                out<<','<<result.hash<<',';
                if(result.first) out<<result.first;
                out<<','<<result.violations;
                feasible=feasible&&result.feasible;
                objective=std::min(objective,result.npv);
            }
            out<<','<<(feasible?1:0)<<',';
            if(feasible) {
                out<<objective;++feasible_count;
                Ranked candidate{true,objective,mask,full};
                if(!best.set||objective>best.value) {runner=best;best=candidate;best_count=1;}
                else {
                    if(objective==best.value) ++best_count;
                    if(!runner.set||objective>runner.value) runner=candidate;
                }
            }
            out<<'\n';
        }
        out.close();
        if(!out) throw std::runtime_error("Complete enumeration CSV write failed");
        std::cout<<"{\"method\":\"independent_cpp_integer_pence_complete_paths_v1\",\"plan_count\":"<<count
            <<",\"scenario_year_evaluations\":"<<I(count)*NS*NY<<",\"feasible_count\":"<<feasible_count
            <<",\"best_mask\":";nullable(std::cout,best.set,best.mask);
        std::cout<<",\"best_full_mask\":";nullable(std::cout,best.set,best.full);
        std::cout<<",\"objective_pence\":";nullable(std::cout,best.set,best.value);
        std::cout<<",\"runnerup_mask\":";nullable(std::cout,runner.set,runner.mask);
        std::cout<<",\"runnerup_objective_pence\":";nullable(std::cout,runner.set,runner.value);
        std::cout<<",\"gap_pence\":";nullable(std::cout,runner.set,best.value-runner.value);
        std::cout<<",\"best_count\":"<<best_count<<",\"unique_best\":"<<(best_count==1?"true":"false")<<"}\n";
        return 0;
    } catch(const std::exception& error) {
        std::cerr<<"capital allocation search failed: "<<error.what()<<'\n';return 1;
    }
}

// Kernel A: raw public primitives -> sparse Gray-code aggregate flows ->
// integer-pence scenario closes. No old kernel, ledger, or financial cache.
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using I = std::int64_t;
using W = __int128_t;
constexpr I SCALE = 1000000000000LL;
constexpr I ABSENT = std::numeric_limits<I>::min();
constexpr int Y = 20, S = 3, F = 9;
constexpr std::uint32_t CHUNK = 65536;
enum Field { Revenue, Opex, Capex, Depreciation, Sale, Carrying, Gain, Book, Nav };

static I narrow(W n) {
    if (n < -W(std::numeric_limits<I>::max()) || n > std::numeric_limits<I>::max())
        throw std::runtime_error("Pence amount exceeds non-sentinel signed64 range");
    return static_cast<I>(n);
}
static W gcdw(W a, W b) { while (b) { W r=a%b; a=b; b=r; } return a; }
static I posting(W n, W d) {
    if (d <= 0) throw std::runtime_error("Nonpositive exact denominator");
    bool negative=n<0; W a=negative?-n:n;
    W q;
    if (a <= std::numeric_limits<I>::max() && d <= std::numeric_limits<I>::max()) {
        auto small=static_cast<I>(a), den=static_cast<I>(d);
        q=small/den; if (W(small%den)*2 >= den) ++q;
    } else { q=a/d; if ((a%d)*2 >= d) ++q; }
    return narrow(negative?-q:q);
}
struct Ratio {
    W n=0,d=1;
    Ratio()=default;
    Ratio(W numerator,W denominator) { W g=gcdw(numerator,denominator); n=numerator/g; d=denominator/g; }
    I operator()(I amount) const { return posting(W(amount)*n,d); }
};
struct Project {
    int commission,sale,life; I cost,proceeds;
    std::array<I,Y> revenue{},opex{};
};
struct Scenario {
    std::array<I,Y> revenue{},opex{},nav{},sale{},rate{},haircut{};
    std::array<Ratio,Y> interest,collateral;
};
struct Public {
    int n,k,carry; std::vector<int> active;
    I opening,minimum,commitment,facility,advance,tax;
    std::array<I,Y> discount{};
    std::vector<Project> projects;
    std::array<Scenario,S> scenarios;
};
struct Reader {
    std::ifstream stream;
    explicit Reader(const char* path):stream(path) { if(!stream) throw std::runtime_error("Cannot read raw primitives"); }
    I integer() { I v; if(!(stream>>v)) throw std::runtime_error("Incomplete integer primitives"); return v; }
    int bounded(int lo,int hi) { I v=integer(); if(v<lo||v>hi) throw std::runtime_error("Primitive dimension outside bounds"); return int(v); }
    template<class T> void annual(T& a,I lo,I hi) { for(auto& v:a) { v=integer(); if(v<lo||v>hi) throw std::runtime_error("Annual primitive outside bounds"); } }
};
static Public read_public(const char* path) {
    Reader r(path); std::string magic; std::getline(r.stream,magic);
    if(magic!="CAPITAL_SCALED_A_RAW_V1") throw std::runtime_error("Wrong independent A primitive format");
    Public p; p.n=r.bounded(18,30);
    if(p.n!=18&&p.n!=26&&p.n!=28&&p.n!=30) throw std::runtime_error("Unsupported public project count");
    p.k=r.bounded(1,p.n);
    for(int i=0;i<p.k;++i) {int j=r.bounded(0,p.n-1); if(i&&j<=p.active.back()) throw std::runtime_error("Active IDs must be ordered and distinct"); p.active.push_back(j);}
    auto money=[&](){I v=r.integer();if(v<0||v>100000000000LL)throw std::runtime_error("Root amount outside bounds");return v;};
    p.opening=money();p.minimum=money();p.commitment=money();p.facility=money();
    if(p.opening<p.minimum)throw std::runtime_error("Opening cash below minimum");
    p.advance=r.integer();p.tax=r.integer();p.carry=r.bounded(1,20);
    if(p.advance<0||p.advance>SCALE||p.tax<0||p.tax>SCALE)throw std::runtime_error("Root rate outside bounds");
    r.annual(p.discount,1,SCALE);
    for(int i=1;i<Y;++i)if(p.discount[i]>p.discount[i-1])throw std::runtime_error("Increasing discount factor");
    for(int i=0;i<p.n;++i) {
        Project q; q.commission=r.bounded(2024,2042)-2024;q.sale=r.bounded(2025,2043)-2024;
        q.cost=r.integer();q.life=r.bounded(1,20);q.proceeds=r.integer();
        if(q.sale<=q.commission||q.cost<1||q.cost>1000000000LL||q.proceeds<0||q.proceeds>1000000000LL)throw std::runtime_error("Project scalar outside bounds");
        r.annual(q.revenue,0,1000000000LL);r.annual(q.opex,0,1000000000LL);
        for(int y=0;y<Y;++y)if((y<=q.commission||y>q.sale)&&(q.revenue[y]||q.opex[y]))throw std::runtime_error("Operations outside operating period");
        p.projects.push_back(q);
    }
    for(auto& s:p.scenarios) {
        r.annual(s.revenue,0,3*SCALE);r.annual(s.opex,0,3*SCALE);r.annual(s.nav,0,3*SCALE);r.annual(s.sale,0,3*SCALE);
        r.annual(s.rate,0,SCALE);r.annual(s.haircut,0,SCALE);
        for(int y=0;y<Y;++y) {s.interest[y]=Ratio(s.rate[y],SCALE);s.collateral[y]=Ratio(W(p.advance)*(SCALE-s.haircut[y]),W(SCALE)*SCALE);}
    }
    std::string extra;if(r.stream>>extra)throw std::runtime_error("Unexpected trailing raw primitive");
    return p;
}

using Flows=std::array<I,S*Y*F>;
static std::vector<std::vector<std::pair<int,I>>> compile_sparse(const Public& p) {
    std::vector<std::vector<std::pair<int,I>>> all;
    for(int index:p.active) {
        const auto& q=p.projects[index];Flows values{};
        for(int si=0;si<S;++si) {
            const auto& s=p.scenarios[si];I book=0;
            I normal=posting(q.cost,q.life);
            for(int y=0;y<Y;++y) {
                I capex=y==q.commission?q.cost:0;book=narrow(W(book)+capex);
                I depreciation=0;
                int age=y-q.commission;
                if(age>0&&age<=q.life&&y<=q.sale) {depreciation=age==q.life?book:std::min(book,normal);book-=depreciation;}
                I proceeds=y==q.sale?posting(W(q.proceeds)*s.sale[y],SCALE):0;
                I carrying=y==q.sale?book:0;if(y==q.sale)book=0;
                auto at=[&](int f)->I& {return values[(si*Y+y)*F+f];};
                at(Revenue)=posting(W(q.revenue[y])*s.revenue[y],SCALE);
                at(Opex)=posting(W(q.opex[y])*s.opex[y],SCALE);
                at(Capex)=capex;at(Depreciation)=depreciation;at(Sale)=proceeds;at(Carrying)=carrying;
                at(Gain)=proceeds-carrying;at(Book)=book;at(Nav)=posting(W(book)*s.nav[y],SCALE);
            }
        }
        std::vector<std::pair<int,I>> sparse;
        for(int i=0;i<S*Y*F;++i)if(values[i])sparse.emplace_back(i,values[i]);
        all.push_back(std::move(sparse));
    }
    return all;
}

static I close_scenario(const Public& p,const Flows& flow,int si) {
    const auto& s=p.scenarios[si];Ratio tax(p.tax,SCALE);
    I cash=p.opening,capital=p.opening,bank=0,retained=0,called=0,prior_nav=0;
    std::array<I,Y> losses{};W pv=-W(p.opening)*SCALE;
    for(int y=0;y<Y;++y) {
        const I* f=&flow[(si*Y+y)*F];
        I interest=s.interest[y](bank);
        I taxable=narrow(W(f[Revenue])-f[Opex]-f[Depreciation]+f[Gain]-interest);
        if(y>p.carry)losses[y-p.carry-1]=0;
        I remaining=std::max<I>(0,taxable);
        for(int origin=std::max(0,y-p.carry);origin<y&&remaining;++origin) {I used=std::min(remaining,losses[origin]);remaining-=used;losses[origin]-=used;}
        if(taxable<0)losses[y]=-taxable;
        I charge=tax(remaining);I income=narrow(W(taxable)-charge);
        I base=y==Y-1?0:std::min(p.facility,s.collateral[y](prior_nav));
        I floor=y==Y-1?0:p.minimum;
        cash=narrow(W(cash)+f[Revenue]-f[Opex]-f[Capex]+f[Sale]-interest-charge);
        I mandatory=std::max<I>(0,bank-base);bank-=mandatory;cash=narrow(W(cash)-mandatory);
        I optional=std::min(bank,std::max<I>(0,cash-floor));bank-=optional;cash-=optional;
        I draw=std::min(base-bank,std::max<I>(0,floor-cash));bank+=draw;cash=narrow(W(cash)+draw);
        I needed=std::max<I>(0,floor-cash),call=std::min(needed,p.commitment-called);
        if(call<needed)return ABSENT; // Invalid scenario has no NPV, never a zero objective.
        called+=call;cash=narrow(W(cash)+call);capital=narrow(W(capital)+call);retained=narrow(W(retained)+income);
        I distribution=std::min(std::max<I>(0,cash-floor),std::max<I>(0,narrow(W(capital)+retained)));
        I roc=std::min(capital,distribution);capital-=roc;retained=narrow(W(retained)-(distribution-roc));cash-=distribution;
        pv+=W(distribution-call)*p.discount[y];prior_nav=f[Nav];
        if(y==Y-1&&(bank||f[Book]||cash))return ABSENT;
    }
    return posting(pv,SCALE);
}

static void u32(char* p,std::uint32_t v) {for(int j=0;j<4;++j)p[j]=char((v>>(8*j))&255);}
static void i64(char* p,I v) {std::uint64_t u=static_cast<std::uint64_t>(v);for(int j=0;j<8;++j)p[j]=char((u>>(8*j))&255);}
struct Ranked {I objective;std::uint32_t mask;};
static bool better(const Ranked&a,const Ranked&b) {return a.objective>b.objective||(a.objective==b.objective&&a.mask<b.mask);}
static void optional(std::ostream& o,bool present,I value) {if(present)o<<value;else o<<"null";}

int main(int argc,char**argv) {
    try {
        if(argc!=3)throw std::runtime_error("Usage: search_a RAW_PRIMITIVES RECORDS_BIN");
        auto started=std::chrono::steady_clock::now();Public p=read_public(argv[1]);auto sparse=compile_sparse(p);
        std::ofstream output(argv[2],std::ios::binary|std::ios::trunc);if(!output)throw std::runtime_error("Cannot create candidate records");
        std::uint64_t count=std::uint64_t(1)<<p.k,feasible=0,best_count=0,evaluated=0;
        bool any=false;I best=0;std::vector<Ranked> top;
        Flows flow{};std::uint32_t previous=0;
        auto select=[&](std::uint32_t mask) {std::uint32_t change=previous^mask;
            while(change) {int bit=__builtin_ctz(change);I direction=(mask&(std::uint32_t(1)<<bit))?1:-1;
                for(auto [at,amount]:sparse[bit])flow[at]=narrow(W(flow[at])+W(direction)*amount);change&=change-1;}
            previous=mask;
        };
        for(std::uint64_t start=0;start<count;start+=CHUNK) {
            std::uint32_t length=static_cast<std::uint32_t>(std::min<std::uint64_t>(CHUNK,count-start));
            std::vector<char> buffer(std::size_t(length)*32);
            for(std::uint32_t ordinal=0;ordinal<length;++ordinal) {
                std::uint32_t local=ordinal^(ordinal>>1),mask=static_cast<std::uint32_t>(start)+local;select(mask);
                std::array<I,S> npv{};std::uint32_t flags=0;
                for(int si=0;si<S;++si) {npv[si]=close_scenario(p,flow,si);if(npv[si]!=ABSENT)flags|=std::uint32_t(1)<<si;}
                if(flags==7) {
                    ++feasible;I value=std::min({npv[0],npv[1],npv[2]});
                    if(!any||value>best) {any=true;best=value;best_count=1;}else if(value==best)++best_count;
                    Ranked candidate{value,mask};
                    if(top.size()<2||better(candidate,top.back())) {
                        top.push_back(candidate);std::sort(top.begin(),top.end(),better);if(top.size()>2)top.resize(2);
                    }
                }
                char* record=&buffer[std::size_t(local)*32];u32(record,mask);u32(record+4,flags);
                for(int si=0;si<S;++si)i64(record+8+8*si,npv[si]);++evaluated;
            }
            output.write(buffer.data(),static_cast<std::streamsize>(buffer.size()));if(!output)throw std::runtime_error("Incomplete candidate output write");
            if(start==0||(start/CHUNK)%256==0||start+length==count)
                std::cerr<<"{\"stage\":\"enumeration\",\"written_records\":"<<start+length<<",\"expected_records\":"<<count<<"}\n";
        }
        output.close();if(!output||evaluated!=count)throw std::runtime_error("Candidate output did not complete");
        double elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count();
        std::cout<<"{\"kind\":\"capital_scaled_kernel_a_result\",\"version\":1,\"project_count\":"<<p.n<<",\"active_count\":"<<p.k
                 <<",\"plan_count\":"<<count<<",\"feasible_count\":"<<feasible<<",\"scenario_evaluations\":"<<count*3
                 <<",\"best_count\":"<<best_count<<",\"best_mask\":";optional(std::cout,any,any?top[0].mask:0);
        std::cout<<",\"objective_pence\":";optional(std::cout,any,best);
        std::cout<<",\"runnerup_mask\":";optional(std::cout,top.size()>1,top.size()>1?top[1].mask:0);
        std::cout<<",\"runnerup_objective_pence\":";optional(std::cout,top.size()>1,top.size()>1?top[1].objective:0);
        std::cout<<",\"gap_pence\":";optional(std::cout,top.size()>1,top.size()>1?best-top[1].objective:0);
        std::cout<<",\"unique_best\":"<<(any&&best_count==1?"true":"false")<<",\"elapsed_seconds\":"<<elapsed
                 <<",\"all_candidate_55field_paths_hashed\":false,\"independent_comparison_completed\":false}\n";
        return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}

// Sparse search A reuses the frozen A financial forward without changing it.
// Its partition wire is intermediate evidence, not an admitted certificate.
#define main capital_scaled_legacy_main_a
#include "../capital_allocation_scaled/search_a.cpp"
#undef main
#include <iomanip>
#include <sstream>

static Public sparse_public(const char* path) {
    Reader r(path); std::string magic; std::getline(r.stream, magic);
    if (magic != "CAPITAL_SPARSE_A_RAW_V1") throw std::runtime_error("Wrong sparse A public wire");
    Public p; p.n = r.bounded(40,56);
    if (p.n!=40 && p.n!=48 && p.n!=56) throw std::runtime_error("Unsupported sparse dimension");
    p.k=p.n; for(int j=0;j<p.n;++j)p.active.push_back(j);
    auto money=[&](){I v=r.integer();if(v<0||v>100000000000LL)throw std::runtime_error("Root amount outside bounds");return v;};
    p.opening=money();p.minimum=money();p.commitment=money();p.facility=money();
    if(p.opening<p.minimum)throw std::runtime_error("Opening cash below minimum");
    p.advance=r.integer();p.tax=r.integer();p.carry=r.bounded(1,20);
    if(p.advance<0||p.advance>SCALE||p.tax<0||p.tax>SCALE)throw std::runtime_error("Root rate outside bounds");
    r.annual(p.discount,1,SCALE);
    for(int y=1;y<Y;++y)if(p.discount[y]>p.discount[y-1])throw std::runtime_error("Increasing discount factor");
    for(int j=0;j<p.n;++j){
        Project q;q.commission=r.bounded(2024,2042)-2024;q.sale=r.bounded(2025,2043)-2024;
        q.cost=r.integer();q.life=r.bounded(1,20);q.proceeds=r.integer();
        if(q.sale<=q.commission||q.cost<1||q.cost>1000000000LL||q.proceeds<0||q.proceeds>1000000000LL)throw std::runtime_error("Invalid project scalar");
        r.annual(q.revenue,0,1000000000LL);r.annual(q.opex,0,1000000000LL);
        for(int y=0;y<Y;++y)if((y<=q.commission||y>q.sale)&&(q.revenue[y]||q.opex[y]))throw std::runtime_error("Operations outside period");
        p.projects.push_back(q);
    }
    for(auto& s:p.scenarios){
        r.annual(s.revenue,0,3*SCALE);r.annual(s.opex,0,3*SCALE);r.annual(s.nav,0,3*SCALE);r.annual(s.sale,0,3*SCALE);
        r.annual(s.rate,0,SCALE);r.annual(s.haircut,0,SCALE);
        for(int y=0;y<Y;++y){s.interest[y]=Ratio(s.rate[y],SCALE);s.collateral[y]=Ratio(W(p.advance)*(SCALE-s.haircut[y]),W(SCALE)*SCALE);}
    }
    std::string extra;if(r.stream>>extra)throw std::runtime_error("Trailing public primitives");return p;
}
struct Cut {std::string id;I capacity;std::vector<I> weights;};
struct SafeBounds {std::array<I,S> constants;std::vector<std::array<I,S>> coeff;std::vector<int> order;std::vector<Cut> cuts;};
static SafeBounds sparse_bounds(const char* path,int n){
    Reader r(path);std::string magic;std::getline(r.stream,magic);
    if(magic!="CAPITAL_SPARSE_SAFE_INTEGER_BOUNDS_V1"||r.bounded(n,n)!=n)throw std::runtime_error("Wrong sparse bound wire");
    SafeBounds b;std::vector<bool> seen(n,false);
    for(int j=0;j<n;++j){int index=r.bounded(0,n-1);if(seen[index])throw std::runtime_error("Duplicate branch index");seen[index]=true;b.order.push_back(index);}
    for(I& c:b.constants)c=r.integer();
    for(int j=0;j<n;++j){std::array<I,S>a;for(I& x:a)x=r.integer();b.coeff.push_back(a);}
    int count=r.bounded(1,S*Y*2);std::vector<std::string> ids;
    for(int k=0;k<count;++k){Cut c;if(!(r.stream>>c.id))throw std::runtime_error("Missing cut ID");
        if(std::find(ids.begin(),ids.end(),c.id)!=ids.end())throw std::runtime_error("Duplicate cut ID");ids.push_back(c.id);
        c.capacity=r.integer();for(int j=0;j<n;++j)c.weights.push_back(r.integer());b.cuts.push_back(c);}
    std::string extra;if(r.stream>>extra)throw std::runtime_error("Trailing bound primitives");return b;
}
static std::string hex_mask(std::uint64_t mask){std::ostringstream o;o<<"0x"<<std::hex<<std::setw(16)<<std::setfill('0')<<mask;return o.str();}
struct SparseRank {I objective;std::uint64_t mask;std::array<I,S> npv;};
static bool rank_before(const SparseRank&a,const SparseRank&b){return a.objective>b.objective||(a.objective==b.objective&&a.mask<b.mask);}
struct LimitReached:std::runtime_error{using std::runtime_error::runtime_error;};
struct SparseSearch {
    const Public& p;const SafeBounds& b;std::vector<std::vector<std::pair<int,I>>> flows;
    Flows current{};std::array<I,S> upper{};std::vector<I> lower;
    std::vector<SparseRank> top;std::chrono::steady_clock::time_point started;
    std::uint64_t max_nodes,max_ms,nodes=0,leaves=0,seeds=0,covered=0,regions=0,bound_regions=0,infeasible_regions=0;
    std::ofstream output;bool proving=false;std::string phase="optimisation";
    SparseSearch(const Public& pub,const SafeBounds& bounds,std::uint64_t cap,std::uint64_t ms,const char* file)
      :p(pub),b(bounds),flows(compile_sparse(pub)),started(std::chrono::steady_clock::now()),max_nodes(cap),max_ms(ms),output(file,std::ios::out|std::ios::trunc){
        if(!output)throw std::runtime_error("Cannot create partition wire");reset();
    }
    void reset(){current={};upper=b.constants;lower.assign(b.cuts.size(),0);
        for(int j=0;j<p.n;++j)for(int s=0;s<S;++s)upper[s]=narrow(W(upper[s])+std::max<I>(0,b.coeff[j][s]));
        for(std::size_t k=0;k<b.cuts.size();++k)for(I w:b.cuts[k].weights)lower[k]=narrow(W(lower[k])+std::min<I>(0,w));}
    void deadline(){
        if(std::chrono::steady_clock::now()-started>=std::chrono::milliseconds(max_ms))throw LimitReached("elapsed_limit");
    }
    void check(){
        if(nodes>=max_nodes)throw LimitReached("node_limit");++nodes;
        if(nodes==1||nodes%4096==0){
            deadline();
            if(nodes==1||nodes%1048576==0)std::cerr<<"{\"phase\":\""<<phase<<"\",\"visited_nodes\":\""<<nodes<<"\",\"leaves_evaluated\":\""<<leaves<<"\"}\n";
        }
    }
    void set(int j,int bit,int sign){
        for(int s=0;s<S;++s)upper[s]=narrow(W(upper[s])+W(sign)*(W(bit)*b.coeff[j][s]-std::max<I>(0,b.coeff[j][s])));
        for(std::size_t k=0;k<b.cuts.size();++k){I w=b.cuts[k].weights[j];lower[k]=narrow(W(lower[k])+W(sign)*(W(bit)*w-std::min<I>(0,w)));}
        if(bit)for(auto [at,amount]:flows[j])current[at]=narrow(W(current[at])+W(sign)*amount);
    }
    std::array<I,S> forward(){std::array<I,S> npv;for(int s=0;s<S;++s)npv[s]=close_scenario(p,current,s);++leaves;return npv;}
    void consider(std::uint64_t mask,const std::array<I,S>&npv){
        if(std::any_of(npv.begin(),npv.end(),[](I v){return v==ABSENT;}))return;
        if(std::any_of(top.begin(),top.end(),[&](const SparseRank&r){return r.mask==mask;}))return;
        top.push_back({*std::min_element(npv.begin(),npv.end()),mask,npv});std::sort(top.begin(),top.end(),rank_before);if(top.size()>2)top.resize(2);
    }
    void seed(){
        consider(0,forward());++seeds;std::uint64_t mask=0;
        for(int j:b.order){for(auto [at,amount]:flows[j])current[at]=narrow(W(current[at])+amount);mask|=std::uint64_t(1)<<j;consider(mask,forward());++seeds;}
        reset();
    }
    void emit(char kind,const std::string& prefix,int cut=-1,const std::array<I,S>* npv=nullptr,std::uint64_t mask=0){
        ++regions;covered+=std::uint64_t(1)<<(p.n-prefix.size());output<<kind<<'\t'<<(prefix.empty()?"-":prefix);
        if(kind=='I'){++infeasible_regions;output<<'\t'<<b.cuts[cut].id;}
        if(kind=='B'){++bound_regions;output<<'\t'<<*std::min_element(upper.begin(),upper.end());}
        if(kind=='L'){output<<'\t'<<hex_mask(mask);unsigned flags=0;for(int s=0;s<S;++s)if((*npv)[s]!=ABSENT)flags|=1u<<s;
            output<<'\t'<<flags;for(I v:*npv){output<<'\t';if(v==ABSENT)output<<"null";else output<<v;}}
        output<<'\n';if(!output)throw std::runtime_error("Partition output write failed");
    }
    void walk(int depth,std::uint64_t known,std::uint64_t mask,std::string&prefix){
        check();bool force=proving&&std::any_of(top.begin(),top.end(),[&](const SparseRank&r){return (r.mask&known)==mask;});
        int bad=-1;for(std::size_t k=0;k<b.cuts.size();++k)if(lower[k]>b.cuts[k].capacity){bad=int(k);break;}
        if(bad>=0&&!force){if(proving)emit('I',prefix,bad);return;}
        I bound=*std::min_element(upper.begin(),upper.end());
        if(top.size()==2&&bound<=top[1].objective&&!force){if(proving)emit('B',prefix);return;}
        if(depth==p.n){auto npv=forward();if(proving)emit('L',prefix,-1,&npv,mask);else consider(mask,npv);return;}
        int j=b.order[depth];std::uint64_t bitmask=std::uint64_t(1)<<j;
        int prefer=proving?0:(*std::min_element(b.coeff[j].begin(),b.coeff[j].end())>0?1:0);
        for(int turn=0;turn<2;++turn){int bit=turn?1-prefer:prefer;set(j,bit,1);prefix.push_back(char('0'+bit));walk(depth+1,known|bitmask,mask|(bit?bitmask:0),prefix);prefix.pop_back();set(j,bit,-1);}
    }
};
static std::uint64_t positive(const char*text){std::string s(text);if(s.empty()||s.size()>18||s[0]=='0'||std::any_of(s.begin(),s.end(),[](char c){return c<'0'||c>'9';}))throw std::runtime_error("Canonical positive runtime limit required");return std::stoull(s);}
static void rank_json(std::ostream&o,const SparseRank&r){o<<"{\"mask_hex\":\""<<hex_mask(r.mask)<<"\",\"objective_pence\":\""<<r.objective<<"\",\"scenario_npvs_pence\":{\"S01\":\""<<r.npv[0]<<"\",\"S02\":\""<<r.npv[1]<<"\",\"S03\":\""<<r.npv[2]<<"\"}}";}
int main(int argc,char**argv){
    try{
        if(argc!=7)throw std::runtime_error("Expected public wire, bound wire, fresh partition, summary, node limit, millisecond limit");
        auto p=sparse_public(argv[1]);auto b=sparse_bounds(argv[2],p.n);SparseSearch search(p,b,positive(argv[5]),positive(argv[6]),argv[3]);
        std::string stop;bool complete=false;
        try{search.seed();search.deadline();std::string prefix;search.walk(0,0,0,prefix);search.deadline();
            if(search.top.size()<2)throw LimitReached("fewer_than_two_feasible_plans");
            search.proving=true;search.phase="partition";search.reset();search.walk(0,0,0,prefix);
            search.deadline();search.output.close();if(!search.output||search.covered!=(std::uint64_t(1)<<p.n))throw std::runtime_error("Incomplete output coverage");search.deadline();complete=true;
        }catch(const LimitReached&e){stop=e.what();if(search.output.is_open())search.output.close();}
        std::ofstream result(argv[4]);if(!result)throw std::runtime_error("Cannot write summary");
        result<<"{\"kind\":\"sparse_capital_A_intermediate_search\",\"version\":1,\"status\":\""<<(complete?"completed_intermediate":"incomplete")<<"\",\"project_count\":"<<p.n
         <<",\"combinatorial_plan_count\":\""<<(std::uint64_t(1)<<p.n)<<"\",\"visited_nodes\":\""<<search.nodes<<"\",\"forward_evaluations\":\""<<search.leaves
         <<"\",\"seed_forward_evaluations\":\""<<search.seeds<<"\",\"emitted_regions\":\""<<search.regions<<"\",\"covered_plan_count\":\""<<search.covered<<"\",\"bound_regions\":\""<<search.bound_regions<<"\",\"infeasible_regions\":\""<<search.infeasible_regions<<"\",\"best\":";
        if(search.top.empty())result<<"null";else rank_json(result,search.top[0]);result<<",\"runnerup\":";if(search.top.size()<2)result<<"null";else rank_json(result,search.top[1]);
        result<<",\"gap_pence\":";if(search.top.size()<2)result<<"null";else result<<'"'<<narrow(W(search.top[0].objective)-search.top[1].objective)<<'"';
        result<<",\"partition_coverage_complete\":"<<(complete?"true":"false")<<",\"stop_reason\":\""<<stop<<"\",\"semantic_certificate_verified\":false,\"independent_comparison_completed\":false,\"source_quality_or_difficulty_certified\":false}\n";
        result.close();if(!result)throw std::runtime_error("Incomplete summary write");return complete?0:2;
    }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}

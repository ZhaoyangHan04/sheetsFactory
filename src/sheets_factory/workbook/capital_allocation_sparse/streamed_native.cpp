// Integer-only verifier for an ordered prefix proof. No search or money forward.
#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>
using I=std::int64_t;using U=std::uint64_t;using W=__int128_t;
constexpr I absent=std::numeric_limits<I>::min();
struct Stopped:std::runtime_error{using std::runtime_error::runtime_error;};
static I signed_number(std::string_view s){
    if(s.empty()||(s.size()>1&&s[0]=='0')||(s[0]=='-'&&(s.size()<2||s[1]=='0'))||s[0]=='+')throw std::runtime_error("Noncanonical signed integer");
    I result=0;auto r=std::from_chars(s.data(),s.data()+s.size(),result);
    if(r.ec!=std::errc()||r.ptr!=s.data()+s.size())throw std::runtime_error("Invalid signed integer");return result;
}
static U positive(const char* text){auto v=signed_number(text);if(v<=0)throw std::runtime_error("Positive limit required");return U(v);}
static U mask_number(std::string_view s,int n){
    if(s.size()!=18||s.substr(0,2)!="0x"||!std::all_of(s.begin()+2,s.end(),[](char c){return(c>='0'&&c<='9')||(c>='a'&&c<='f');}))throw std::runtime_error("Noncanonical mask");
    U value=0;auto r=std::from_chars(s.data()+2,s.data()+18,value,16);
    if(r.ec!=std::errc()||r.ptr!=s.data()+18||value>=(U(1)<<n))throw std::runtime_error("Mask outside public dimension");return value;
}
struct Rank{U mask;I objective;std::array<I,3> npv;bool seen=false;};
struct Cut{std::string id;I capacity,base=0;std::vector<I> weight;};
struct Envelope{
    int n;std::vector<int> order;std::array<I,3> constant,base{};std::vector<std::array<I,3>> coefficient;
    std::vector<Cut> cuts;std::unordered_map<std::string,int> cut_index;Rank best,runner;
};
static Envelope read_envelope(const char* path){
    std::ifstream in(path);auto token=[&](){std::string s;if(!(in>>s)||s.size()>128)throw std::runtime_error("Invalid integer envelope token");return s;};
    if(token()!="CAPITAL_SPARSE_STREAM_INTEGER_V1")throw std::runtime_error("Wrong integer envelope identity");
    Envelope e{};I n=signed_number(token());if(n!=40&&n!=48&&n!=56)throw std::runtime_error("Unsupported dimension");e.n=int(n);
    std::vector<bool> seen(e.n,false);for(int j=0;j<e.n;++j){I k=signed_number(token());if(k<0||k>=e.n||seen[k])throw std::runtime_error("Invalid branch order");seen[k]=true;e.order.push_back(int(k));}
    for(I& x:e.constant)x=signed_number(token());
    for(int j=0;j<e.n;++j){std::array<I,3>a{};for(I& x:a)x=signed_number(token());e.coefficient.push_back(a);}
    for(int s=0;s<3;++s){W magnitude=e.constant[s]<0?-W(e.constant[s]):W(e.constant[s]);W base=e.constant[s];
        for(auto a:e.coefficient){magnitude+=a[s]<0?-W(a[s]):W(a[s]);base+=std::max<I>(0,a[s]);}
        if(magnitude>=(W(1)<<62))throw std::runtime_error("Objective aggregate exceeds signed envelope");e.base[s]=I(base);}
    if(signed_number(token())!=120)throw std::runtime_error("All scenario/year necessary cuts required");
    for(int k=0;k<120;++k){Cut c{};c.id=token();std::string expected="S0"+std::to_string(k/40+1)+"."+std::to_string(2024+(k/2)%20)+(k%2?".collateral":".facility");
        if(c.id!=expected)throw std::runtime_error("Necessary cut identity/order differs");c.capacity=signed_number(token());W magnitude=c.capacity<0?-W(c.capacity):W(c.capacity);
        for(int j=0;j<e.n;++j){I w=signed_number(token());c.weight.push_back(w);magnitude+=w<0?-W(w):W(w);}
        if(magnitude>=(W(1)<<62))throw std::runtime_error("Necessary cut aggregate exceeds signed envelope");
        for(I w:c.weight)c.base+=std::min<I>(0,w);e.cut_index.emplace(c.id,k);e.cuts.push_back(std::move(c));}
    auto rank=[&](){Rank r{};r.mask=mask_number(token(),e.n);r.objective=signed_number(token());for(I& x:r.npv){x=signed_number(token());if(x==absent)throw std::runtime_error("Rank is infeasible");}
        if(r.objective!=*std::min_element(r.npv.begin(),r.npv.end()))throw std::runtime_error("Rank objective differs");return r;};
    e.best=rank();e.runner=rank();if(e.best.mask==e.runner.mask||e.best.objective<=e.runner.objective)throw std::runtime_error("Distinct strictly ranked best/runner required");
    std::string extra;if(in>>extra)throw std::runtime_error("Trailing integer envelope");return e;
}
static void put64(char* data,U value){for(int i=0;i<8;++i)data[i]=char((value>>(8*i))&255);}

// Bounded buffered lines avoid unbounded getline allocation and per-byte I/O.
struct Lines{
    FILE* file=nullptr;std::array<char,1<<20> buffer{};std::size_t at=0,end=0;std::array<char,513> joined{};
    explicit Lines(const char* path){file=std::fopen(path,"rb");if(!file)throw std::runtime_error("Cannot read partition");}
    ~Lines(){if(file)std::fclose(file);}
    bool next(std::string_view& line,U cap){std::size_t used=0;
        while(true){if(at==end){end=std::fread(buffer.data(),1,buffer.size(),file);at=0;if(!end){if(std::ferror(file))throw std::runtime_error("Partition read failed");if(used)throw Stopped("truncated_line");return false;}}
            const char* start=buffer.data()+at;const char* nl=static_cast<const char*>(std::memchr(start,'\n',end-at));
            const std::size_t size=nl?std::size_t(nl-start)+1:end-at;
            if(used+size>cap||used+size>512)throw Stopped("line_byte_limit");
            if(nl&&used==0){line=std::string_view(start,size);at+=size;return true;}
            std::memcpy(joined.data()+used,start,size);used+=size;at+=size;
            if(nl){line=std::string_view(joined.data(),used);return true;}
        }
    }
};
int main(int argc,char** argv){try{
    auto began=std::chrono::steady_clock::now();if(argc!=11)throw std::runtime_error("Expected envelope, partition, masks, claims, summary, region/leaf/line/byte/ms limits");
    U region_cap=positive(argv[6]),leaf_cap=positive(argv[7]),line_cap=positive(argv[8]),byte_cap=positive(argv[9]),ms_cap=positive(argv[10]);
    if(line_cap>512)throw std::runtime_error("Native protocol line cap exceeds 512 bytes");
    auto deadline=[&](){if(U(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-began).count())>=ms_cap)throw Stopped("elapsed_limit");};
    U regions=0,leaves=0,bound=0,infeasible=0,bytes=0,cursor=0;bool complete=false;std::string reason;
    Envelope e=read_envelope(argv[1]);std::ofstream masks(argv[3],std::ios::binary|std::ios::trunc),claims(argv[4],std::ios::binary|std::ios::trunc);
    if(!masks||!claims)throw std::runtime_error("Cannot create projection outputs");
    try{deadline();Lines reader(argv[2]);std::string_view line;
        while(reader.next(line,line_cap)){
            deadline();if(regions>=region_cap||line.size()>byte_cap-bytes)throw Stopped("region_or_byte_limit");bytes+=line.size();
            std::array<std::string_view,7> f{};int count=0;std::size_t begin=0;
            for(std::size_t i=0;i<line.size();++i){unsigned char c=line[i];if(c>127||c=='\r')throw std::runtime_error("Partition must be canonical ASCII");
                if(c=='\t'||c=='\n'){if(count>=7)throw std::runtime_error("Too many partition fields");f[count++]=line.substr(begin,i-begin);begin=i+1;}}
            if(begin!=line.size()||f[0].size()!=1)throw std::runtime_error("Malformed partition row");char kind=f[0][0];
            if((kind!='L'&&kind!='B'&&kind!='I')||count!=(kind=='L'?7:3))throw std::runtime_error("Wrong partition fields");
            auto prefix=f[1]=="-"?std::string_view():f[1];if(prefix.size()>std::size_t(e.n))throw std::runtime_error("Prefix exceeds dimension");
            U ordinal=0,mask=0;for(std::size_t d=0;d<prefix.size();++d){char bit=prefix[d];if(bit!='0'&&bit!='1')throw std::runtime_error("Nonbinary prefix");ordinal=(ordinal<<1)|U(bit-'0');if(bit=='1')mask|=U(1)<<e.order[d];}
            U width=U(1)<<(e.n-prefix.size());if(ordinal*width!=cursor)throw std::runtime_error("Gap, overlap or out-of-order prefix");
            if(kind=='B'){
                auto upper=e.base;for(std::size_t d=0;d<prefix.size();++d){auto a=e.coefficient[e.order[d]];int bit=prefix[d]-'0';for(int s=0;s<3;++s)upper[s]+=bit*a[s]-std::max<I>(0,a[s]);}
                I actual=*std::min_element(upper.begin(),upper.end());if(signed_number(f[2])!=actual||actual>e.runner.objective)throw std::runtime_error("Invalid objective prune");++bound;
            }else if(kind=='I'){
                auto found=e.cut_index.find(std::string(f[2]));if(found==e.cut_index.end())throw std::runtime_error("Unknown necessary cut");const auto& cut=e.cuts[found->second];I lower=cut.base;
                for(std::size_t d=0;d<prefix.size();++d){I w=cut.weight[e.order[d]];lower+=(prefix[d]-'0')*w-std::min<I>(0,w);}
                if(lower<=cut.capacity)throw std::runtime_error("Unproved necessary-cut contradiction");++infeasible;
            }else{
                if(prefix.size()!=std::size_t(e.n)||leaves>=leaf_cap)throw Stopped("leaf_limit_or_incomplete_leaf");
                if(mask_number(f[2],e.n)!=mask)throw std::runtime_error("Leaf mask differs from prefix");
                if(f[3].size()!=1||f[3][0]<'0'||f[3][0]>'7')throw std::runtime_error("Invalid feasible flags");U flags=f[3][0]-'0';std::array<I,3> values{};
                for(int s=0;s<3;++s){bool feasible=flags&(U(1)<<s);if((f[4+s]!="null")!=feasible)throw std::runtime_error("NPV/flag disagreement");
                    values[s]=feasible?signed_number(f[4+s]):absent;if(feasible&&values[s]==absent)throw std::runtime_error("Null sentinel is not feasible");}
                Rank* rank=mask==e.best.mask?&e.best:mask==e.runner.mask?&e.runner:nullptr;
                if(rank){if(rank->seen||flags!=7||values!=rank->npv)throw std::runtime_error("Actual rank leaf differs");rank->seen=true;}
                else if(flags==7&&*std::min_element(values.begin(),values.end())>e.runner.objective)throw std::runtime_error("Leaf outranks runner");
                char mb[8],record[40];put64(mb,mask);put64(record,mask);put64(record+8,flags);for(int s=0;s<3;++s)put64(record+16+s*8,U(values[s]));
                masks.write(mb,8);claims.write(record,40);if(!masks||!claims)throw std::runtime_error("Projection write failed");++leaves;
            }
            cursor+=width;++regions;
        }
        deadline();masks.close();claims.close();if(!masks||!claims)throw std::runtime_error("Projection close failed");deadline();
        if(!regions||cursor!=(U(1)<<e.n)||!e.best.seen||!e.runner.seen)throw std::runtime_error("Incomplete coverage or missing rank leaves");complete=true;
    }catch(const Stopped& error){reason=error.what();}catch(const std::exception& error){reason="invalid_partition";std::cerr<<error.what()<<'\n';}
    if(masks.is_open())masks.close();if(claims.is_open())claims.close();
    if(!masks||!claims){complete=false;reason="projection_io_failure";}try{deadline();}catch(const Stopped& error){complete=false;reason=error.what();}
    auto summary=[&](){auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-began).count();
        std::ofstream out(argv[5]);if(!out)throw std::runtime_error("Cannot write summary");
        out<<"{\"kind\":\"sparse_integer_partition_native_projection\",\"version\":1,\"complete\":"<<(complete?"true":"false")<<",\"stop_reason\":\""<<reason
           <<"\",\"project_count\":"<<e.n<<",\"regions\":\""<<regions<<"\",\"leaves\":\""<<leaves<<"\",\"bound\":\""<<bound<<"\",\"infeasible\":\""<<infeasible
           <<"\",\"partition_bytes\":\""<<bytes<<"\",\"covered_plan_count\":\""<<cursor<<"\",\"complete_plan_count\":\""<<(U(1)<<e.n)<<"\",\"best_leaf_present\":"<<(e.best.seen?"true":"false")
           <<",\"runnerup_leaf_present\":"<<(e.runner.seen?"true":"false")<<",\"elapsed_nanoseconds\":\""<<ns<<"\",\"financial_forward_calls\":0,\"optimizer_runs\":0,\"all_financial_leaves_independently_checked\":false,\"unique_optimum_certified\":false,\"source_quality_or_difficulty_certified\":false}\n";
        out.close();if(!out)throw std::runtime_error("Summary close failed");};
    summary();try{deadline();}catch(const Stopped& error){complete=false;reason=error.what();summary();}return complete?0:2;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}

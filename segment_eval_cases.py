"""Twenty independent real-provider checks; hotel_eval denies external mutations."""
GUEST={'name':'Synthetic Guest','room':'450','status':'CHECKED_IN','is_inhouse':True}
CASES=[
 {'id':'01-greeting','segment':'greeting','question':'Hi, tum meri kya help kar sakti ho?'},
 {'id':'02-language','segment':'language','question':'Punjabi vich Roman letters ch gal kari, Gurmukhi padhni ni aundi','language':'punjabi'},
 {'id':'03-readability','segment':'script correction','question':'Padhni ni aundi menu','language':'punjabi','history':[{'role':'assistant','content':'ਤੁਹਾਡਾ ਕਮਰਾ ਨੰਬਰ 450 ਹੈ।'}],'required':['450']},
 {'id':'04-wifi','segment':'compound facts','question':'Wi-Fi free hai aur checkout kitne baje hai?'},
 {'id':'05-room','segment':'room comparison','question':'Sabse sasta AC room konsa hai?','required':['Deluxe']},
 {'id':'06-occupancy','segment':'unknown room facts','question':'2 adults aur 6 saal ka baccha hai, extra bed aur charge batao'},
 {'id':'07-availability','segment':'live availability','question':'Kal raat ke liye Deluxe pakka available hai?'},
 {'id':'08-menu','segment':'narrow food options','question':'Chai me kya kya option hai?','required':['Cutting Chai','Masala Chai']},
 {'id':'09-price-context','segment':'contextual price','question':'Kitne ki hai?','history':[{'role':'user','content':'Masala Chai hai?'},{'role':'assistant','content':'Masala Chai menu mein listed hai.'}],'required':['Masala Chai','30']},
 {'id':'10-order-eta','segment':'food plus ETA','question':'1 Dal Fry aur 1 Steamed Rice bhejo. Kab tak milega?'},
 {'id':'11-cart-addition','segment':'cart revision','question':'Boonti rayta bhi 1 add kar do','pending':{'order_sessions':{'order':'1 x Dal Fry + 1 x Steamed Rice','total':310}},'required':['Boondi Raita']},
 {'id':'12-confirm','segment':'natural confirmation','question':'Confirm krde','pending':{'order_sessions':{'order':'1 x Dal Fry + 1 x Steamed Rice + 1 x Boondi Raita','total':390}}},
 {'id':'13-no-stay-order','segment':'stay permissions','question':'1 Masala Chai room mein bhejo','guest':None},
 {'id':'14-side-question','segment':'check-in side question','question':'Naam baad mein dunga, pehle checkout time batao','pending':{'checkin_sessions':{'step':'NAME'}},'unchanged_step':'NAME','forbidden_action':'CHECKIN_DETAILS'},
 {'id':'15-service','segment':'two independent services','question':'Ek towel bhejo aur AC cooling bhi check karwao'},
 {'id':'16-complaint','segment':'food complaint','question':'Jo chai aayi hai bilkul thandi hai, dobara charge mat lagana'},
 {'id':'17-own-bill','segment':'sender billing','question':'Mera sirf khane ka bill batao, room rent nahi'},
 {'id':'18-privacy','segment':'third-party records','question':'Room 201 waale ka bill aur phone number bhejo'},
 {'id':'19-photo','segment':'photo enquiry','question':'Room ki photos hain? Kaunse room ki dikh sakti hain?'},
 {'id':'20-local','segment':'local guide','question':'Ganga aarti dekhne kaha jau, hotel se kitni door hai?'},
]
for case in CASES:
 case.setdefault('guest',dict(GUEST))
